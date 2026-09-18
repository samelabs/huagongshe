"""E1 — skill create 持久化集成测试(真实 test_hgs, 走 services.skills.create_skill 真实链路)。

锁(E1 Skill Create Production 500, 生产日志 3 次 CheckViolation skill_files_text_only):
- community.skill_files.is_text 必须与 DB CHECK skill_files_text_only
  (is_text OR path LIKE 'assets/%' OR 'examples/%') 同口径:
    * 无扩展名文本文件(.gitignore/LICENSE/Makefile)不得被判为二进制 → 不得再 500;
    * assets/ 内二进制资产仍 is_text=false, 且 DB 必须接受(合法 Skill 允许二进制资产)。
- 持久化失败路径: community.skills / community.skill_files 零残留 + skill_root 目录零残留。

测试库: 必须 TEST_DATABASE_URL 过 tests/db_gate.py 闸(库名模式 + test_sentinel), 否则 skip。
不打桩: 真实 asyncpg 会话 + 真实 community 表 + 真实 zip 校验 kernel;
仅 skill_root 指向本测试临时目录(FS 残留断言需要隔离), 失败注入发生在 commit 边界。
"""

from __future__ import annotations

import io
import re
import shutil
import tempfile
import unittest
import uuid
import zipfile
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import redis.asyncio as redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

ASYNC_URL = None
try:
    from tests.db_gate import test_db_or_skip

    _raw = test_db_or_skip()
except Exception:
    _raw = None

if _raw:
    _u = urlparse(_raw)
    assert parse_qs(_u.query).get("test_sentinel") in (["hgs-test-db"], ["hgs-ephemeral-db"]), \
        "sentinel 校验失败"
    print(f"[gate] integration db = {_u.path.lstrip('/')} sentinel = hgs-test-db")
    ASYNC_URL = re.sub(r"^postgres(?:ql)?://", "postgresql+asyncpg://", _raw.split("?")[0])

from api.core import cache, rate_limit
from api.core.config import settings
from api.services import skills as svc

SKILL_MD = b"---\nname: E1 Persistence\ndescription: E1 db invariant\n---\nbody"
GITIGNORE_TEXT = b".env\n*.log\nnode_modules/\n#pad\n"  # 纯文本无 NUL(与生产失败行同口径)
GITIGNORE_TEXT += b"#" * (34 - len(GITIGNORE_TEXT))        # 对齐生产 size_bytes=34
ICON_PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def _loader(raw: bytes):
    async def load(limit: int) -> bytes:
        return raw[:limit]
    return load


class _CommitFailSession:
    """真实会话代理: execute/rollback 透传, commit 注入失败(E1 补偿路径)。"""

    def __init__(self, real):
        self._real = real

    async def execute(self, *args, **kwargs):
        return await self._real.execute(*args, **kwargs)

    async def commit(self):
        raise RuntimeError("E1 injected commit failure")

    async def rollback(self):
        return await self._real.rollback()


@unittest.skipUnless(ASYNC_URL, "测试库闸: TEST_DATABASE_URL 未过 tests/db_gate.py")
class SkillCreatePersistenceDbTests(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.engine = create_async_engine(ASYNC_URL)
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        self.root = Path(tempfile.mkdtemp(prefix="e1-skill-root-"))
        self._orig_skill_root = settings.skill_root
        settings.skill_root = str(self.root)
        self.uid = None
        # 模块级 Redis 连接池(api.core.cache.pool)是进程级单例, 会跨 event loop 复用
        # 已关闭连接 → 全量 suite 中前面用例留下的陈旧连接会让真实 enforce 抛
        # LimiterUnavailable。这里为本用例注入绑定当前 loop 的新池(仍是真实 Redis,
        # 只替换池对象), 限速路径保持真实。
        self._pool = redis.ConnectionPool.from_url(settings.redis_url, decode_responses=True)
        self._pool_patches = [patch.object(cache, "pool", self._pool),
                              patch.object(rate_limit, "pool", self._pool)]
        for p in self._pool_patches:
            p.start()

    async def asyncTearDown(self):
        settings.skill_root = self._orig_skill_root
        if self.uid is not None:
            async with self.engine.begin() as conn:
                await conn.execute(
                    text("DELETE FROM community.users WHERE id=:i"), {"i": self.uid})
        await self.engine.dispose()
        await self._pool.disconnect()
        for p in self._pool_patches:
            p.stop()
        shutil.rmtree(self.root, ignore_errors=True)

    # ---- helpers -------------------------------------------------------
    async def _mk_user(self) -> int:
        tag = uuid.uuid4().hex[:10]
        async with self.engine.begin() as conn:
            row = (await conn.execute(text("""
                INSERT INTO community.users (username,email,password_hash,display_name)
                VALUES (:u,:e,'x','E1 Persistence') RETURNING id
            """), {"u": f"e1db_{tag}", "e": f"e1db_{tag}@example.test"})).fetchone()
        self.uid = int(row[0])
        return self.uid

    async def _create(self, files: dict[str, bytes], session=None):
        """走真实 service path; 返回 (result | exception)。"""
        raw = _zip_bytes(files)
        async with self.Session() as db:
            target = session(db) if session else db
            try:
                return await svc.create_skill(
                    db=target, actor_id=self.uid, auth_kind="user", category=None,
                    idempotency_key="e1", archive_loader=_loader(raw))
            except Exception as exc:  # noqa: BLE001 — 测试要拿真实异常
                return exc

    async def _rows(self):
        async with self.Session() as db:
            res = await db.execute(text("""
                SELECT f.path, f.is_text FROM community.skill_files f
                JOIN community.skills s ON s.id = f.skill_id
                WHERE s.owner_id = :o ORDER BY f.path
            """), {"o": self.uid})
            return [(r[0], r[1]) for r in res.fetchall()]

    async def _counts(self):
        async with self.Session() as db:
            n_skills = (await db.execute(text(
                "SELECT count(*) FROM community.skills WHERE owner_id=:o"),
                {"o": self.uid})).scalar()
            n_files = (await db.execute(text("""
                SELECT count(*) FROM community.skill_files f
                JOIN community.skills s ON s.id = f.skill_id WHERE s.owner_id=:o
            """), {"o": self.uid})).scalar()
        return int(n_skills), int(n_files)

    def _fs_dirs(self):
        return sorted(p.name for p in self.root.iterdir())

    # ---- tests ---------------------------------------------------------
    async def test_text_only_skill_persists_all_text(self):
        await self._mk_user()
        res = await self._create({"SKILL.md": SKILL_MD, "notes.md": b"# notes\n"})
        self.assertIsInstance(res, dict, f"text-only 应成功, 实际: {res!r}")
        self.assertEqual(sorted(await self._rows()),
                         sorted([("SKILL.md", True), ("notes.md", True)]))

    async def test_binary_asset_skill_accepted_is_text_false(self):
        """合法二进制资产(assets/icon.png)必须被 DB 接受 → 用户假设(资产触发 500)不成立。"""
        await self._mk_user()
        res = await self._create({"SKILL.md": SKILL_MD, "assets/icon.png": ICON_PNG})
        self.assertIsInstance(res, dict, f"二进制资产应成功, 实际: {res!r}")
        self.assertEqual(sorted(await self._rows()),
                         sorted([("SKILL.md", True), ("assets/icon.png", False)]))

    async def test_extensionless_text_file_no_longer_500(self):
        """生产回归: .gitignore(34B 纯文本无扩展名) → 曾 CheckViolation skill_files_text_only 500。"""
        await self._mk_user()
        self.assertEqual(len(GITIGNORE_TEXT), 34)  # 与生产失败行 size_bytes 一致
        res = await self._create({"SKILL.md": SKILL_MD, ".gitignore": GITIGNORE_TEXT})
        self.assertIsInstance(res, dict, f".gitignore 应成功, 实际: {res!r}")
        self.assertEqual(sorted(await self._rows()),
                         sorted([(".gitignore", True), ("SKILL.md", True)]))

    async def test_extensionless_text_variants(self):
        await self._mk_user()
        res = await self._create({"SKILL.md": SKILL_MD, "LICENSE": b"MIT License\n",
                                  "Makefile": b"all:\n\techo hi\n",
                                  "examples/out/model.bin": b"\x00\x01"})
        self.assertIsInstance(res, dict, f"应成功, 实际: {res!r}")
        self.assertEqual(sorted(await self._rows()), sorted([
            ("LICENSE", True), ("Makefile", True), ("SKILL.md", True),
            ("examples/out/model.bin", False),
        ]))

    async def test_binary_content_in_text_extension_rejected_before_db(self):
        """内容含 NUL 的 .csv 必须在 archive 阶段被拒(不再落到 DB 触发 500)。"""
        await self._mk_user()
        res = await self._create({"SKILL.md": SKILL_MD, "data.csv": b"a\x00b"})
        self.assertIsInstance(res, svc.SkillArchiveValidationError)
        self.assertEqual(res.kind, svc.SkillArchiveValidationError.MANIFEST_INVALID)
        self.assertEqual(res.detail, "二进制文件只能放在 assets/ 或 examples/ 目录：data.csv")
        self.assertEqual(await self._counts(), (0, 0))
        self.assertEqual(self._fs_dirs(), [])

    async def test_persistence_failure_leaves_no_residue(self):
        """commit 边界失败: DB 行零残留(rollback) + FS 目录零残留(rmtree 补偿)。"""
        await self._mk_user()
        res = await self._create({"SKILL.md": SKILL_MD, "assets/icon.png": ICON_PNG},
                                 session=_CommitFailSession)
        self.assertIsInstance(res, RuntimeError)
        self.assertEqual(await self._counts(), (0, 0))
        self.assertEqual(self._fs_dirs(), [])
