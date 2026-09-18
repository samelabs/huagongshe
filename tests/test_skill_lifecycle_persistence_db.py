"""E4 — Skill lifecycle 真实状态转换(真实 test_hgs, 真实 service 链路)。

与 hermetic fault-injection 文件互补: 这里不做桩, 用真实 asyncpg 会话 + 真实
community.skills / community.skill_files + 真实 skill_root 目录, 断言"调用方看到
的结果"与"DB 行状态 / canonical 目录 / tombstone 残留"三者一致:

- delete 成功契约: DB 行不再存在 AND canonical 目录不再存在 AND tombstone 零残留;
- delete commit 失败: DB 行仍在 AND canonical 目录被恢复(内容完整) AND 无 tombstone;
- delete DB exists + FS missing: 按冻结 contract 成功(无可清理对象);
- delete DB missing + FS exists(orphan): 404 且**不**动 FS(E4 不引入后台清理 job);
- repeated delete: 保持既有 API contract(404), 不改语义;
- update 只做 DB metadata mutation: 正常提交可见、commit 失败无半更新、校验失败零写。

测试库: 必须 TEST_DATABASE_URL 过 tests/db_gate.py 闸, 否则 skip(既有 skip 基线内)。
"""

from __future__ import annotations

import io
import os
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

SKILL_MD = b"---\nname: E4 Lifecycle\ndescription: E4 lifecycle db invariant\n---\nbody"
GITIGNORE_TEXT = b".env\n*.log\nnode_modules/\n#pad\n"
GITIGNORE_TEXT += b"#" * (34 - len(GITIGNORE_TEXT))
ICON_PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"

FILES = {"SKILL.md": SKILL_MD, ".gitignore": GITIGNORE_TEXT, "assets/icon.png": ICON_PNG}


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
    """真实会话代理: execute/rollback 透传, commit 注入失败(E4 补偿路径)。"""

    def __init__(self, real):
        self._real = real

    async def execute(self, *args, **kwargs):
        return await self._real.execute(*args, **kwargs)

    async def commit(self):
        raise RuntimeError("E4 injected commit failure")

    async def rollback(self):
        return await self._real.rollback()


@unittest.skipUnless(ASYNC_URL, "测试库闸: TEST_DATABASE_URL 未过 tests/db_gate.py")
class SkillLifecyclePersistenceDbTests(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.engine = create_async_engine(ASYNC_URL)
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        self.root = Path(tempfile.mkdtemp(prefix="e4-skill-root-"))
        self._orig_skill_root = settings.skill_root
        settings.skill_root = str(self.root)
        self.uid = None
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
        os.chmod(self.root, 0o755)          # 故障注入用例会临时锁 root
        shutil.rmtree(self.root, ignore_errors=True)

    # ---- helpers -------------------------------------------------------
    async def _mk_user(self) -> int:
        tag = uuid.uuid4().hex[:10]
        async with self.engine.begin() as conn:
            row = (await conn.execute(text("""
                INSERT INTO community.users (username,email,password_hash,display_name)
                VALUES (:u,:e,'x','E4 Lifecycle') RETURNING id
            """), {"u": f"e4db_{tag}", "e": f"e4db_{tag}@example.test"})).fetchone()
        self.uid = int(row[0])
        return self.uid

    async def _create(self, files: dict[str, bytes] | None = None) -> int:
        if self.uid is None:
            await self._mk_user()
        raw = _zip_bytes(files or FILES)
        async with self.Session() as db:
            res = await svc.create_skill(
                db=db, actor_id=self.uid, auth_kind="user", category=None,
                idempotency_key="e4", archive_loader=_loader(raw))
        return int(res["id"])

    async def _counts(self, sid: int) -> tuple[int, int]:
        async with self.engine.connect() as conn:
            skills = (await conn.execute(text(
                "SELECT count(*) FROM community.skills WHERE id=:i"), {"i": sid})).scalar()
            files = (await conn.execute(text(
                "SELECT count(*) FROM community.skill_files WHERE skill_id=:i"),
                {"i": sid})).scalar()
        return int(skills), int(files)

    def _canonical(self, sid: int) -> Path:
        return Path(settings.skill_root) / str(sid)

    def _tombstones(self) -> list[str]:
        return sorted(p.name for p in Path(settings.skill_root).iterdir()
                      if p.name.startswith(".deleted-"))

    # ---- delete matrix -------------------------------------------------
    async def test_delete_success_db_and_fs_both_gone(self):
        sid = await self._create()
        self.assertTrue(self._canonical(sid).is_dir(), "前置: canonical 目录存在")
        self.assertEqual(await self._counts(sid), (1, 3))

        async with self.Session() as db:
            out = await svc.delete_skill_lifecycle(db, sid)

        self.assertIsNone(out)
        self.assertEqual(await self._counts(sid), (0, 0), "DB 行 + skill_files 全清")
        self.assertFalse(self._canonical(sid).exists(), "canonical FS 必须消失")
        self.assertEqual(self._tombstones(), [], "tombstone 零残留")

    async def test_delete_commit_failure_keeps_row_and_restores_fs(self):
        sid = await self._create()
        before = {p.name: p.read_bytes() for p in sorted(self._canonical(sid).rglob("*"))
                  if p.is_file()}

        async with self.Session() as real:
            db = _CommitFailSession(real)
            with self.assertRaises(RuntimeError) as ctx:
                await svc.delete_skill_lifecycle(db, sid)
            self.assertEqual(str(ctx.exception), "E4 injected commit failure",
                             "DB 异常必须原样冒泡, 不得被包装成成功")

        self.assertEqual(await self._counts(sid), (1, 3), "DB 行必须仍在")
        after = {p.name: p.read_bytes() for p in sorted(self._canonical(sid).rglob("*"))
                 if p.is_file()}
        self.assertEqual(after, before, "canonical FS 必须被恢复且内容完整")
        self.assertEqual(self._tombstones(), [], "回滚成功后不得留 tombstone")

    async def test_delete_db_exists_fs_missing_is_success(self):
        sid = await self._create()
        shutil.rmtree(self._canonical(sid))

        async with self.Session() as db:
            await svc.delete_skill_lifecycle(db, sid)

        self.assertEqual(await self._counts(sid), (0, 0))
        self.assertFalse(self._canonical(sid).exists())
        self.assertEqual(self._tombstones(), [], "无可暂存对象 → 不得造 tombstone")

    async def test_repeated_delete_is_404_and_fs_untouched(self):
        sid = await self._create()
        async with self.Session() as db:
            await svc.delete_skill_lifecycle(db, sid)
        async with self.Session() as db:
            with self.assertRaises(svc.SkillNotFoundError) as ctx:
                await svc.delete_skill_lifecycle(db, sid)
        self.assertEqual(str(ctx.exception), "技能不存在", "既有 API contract: 404 原文")
        self.assertEqual(self._tombstones(), [])
        self.assertFalse(self._canonical(sid).exists())

    async def test_orphan_fs_without_db_row_is_not_purged(self):
        """DB 无行 + FS 有目录: 404 且不动 FS(E4 不引入后台 orphan 清理 job)。"""
        sid = await self._create()
        async with self.engine.begin() as conn:
            await conn.execute(text("DELETE FROM community.skills WHERE id=:i"), {"i": sid})
        self.assertEqual(await self._counts(sid), (0, 0))
        self.assertTrue(self._canonical(sid).is_dir())

        async with self.Session() as db:
            with self.assertRaises(svc.SkillNotFoundError):
                await svc.delete_skill_lifecycle(db, sid)

        self.assertTrue(self._canonical(sid).is_dir(), "无 DB 行时不得删 FS")
        self.assertEqual(self._tombstones(), [], "不得留下 tombstone")

    def _stage_then_lock(self):
        """真实 stage(真 rename)成功后锁死 skill_root —— 让后续真实 FS 操作失败。

        用于在真实 DB 上制造 RESTORE_FAILED / PURGE_FAILED: 故障来自真实 OS
        权限(EACCES), 不是 mock。
        """
        real = svc._stage_skill_dir

        def hook(skill_id):
            tomb = real(skill_id)
            os.chmod(settings.skill_root, 0o500)
            return tomb
        return hook

    async def test_delete_restore_failure_is_explicit_and_diagnosable(self):
        sid = await self._create()
        before = {p.name: p.read_bytes() for p in sorted(self._canonical(sid).rglob("*"))
                  if p.is_file()}
        try:
            async with self.Session() as real:
                db = _CommitFailSession(real)
                with patch.object(svc, "_stage_skill_dir", self._stage_then_lock()):
                    with self.assertRaises(svc.SkillFilesystemError) as ctx:
                        await svc.delete_skill_lifecycle(db, sid)
            exc = ctx.exception
            self.assertEqual(exc.kind, svc.SkillFilesystemError.RESTORE_FAILED)
            self.assertIn("E4 injected commit failure", str(exc),
                          "detail 必须带原始 DB 失败原文")
            # 精确状态断言: DB 仍在 / canonical 缺失 / tombstone 存在
            self.assertEqual(await self._counts(sid), (1, 3), "DB 行必须仍在")
            self.assertFalse(self._canonical(sid).exists(), "canonical 目录已缺失")
            tombs = self._tombstones()
            self.assertEqual(len(tombs), 1, "残留必须是唯一可识别 tombstone")
            self.assertIn(tombs[0], str(exc),
                          "detail 必须携带 tombstone 路径(可诊断/可人工恢复)")
            # 残留 tombstone 仍保有原始内容 → 人工 rename 回 canonical 即可恢复
            tomb = Path(settings.skill_root) / tombs[0]
            restored = {p.name: p.read_bytes() for p in sorted(tomb.rglob("*"))
                        if p.is_file()}
            self.assertEqual(restored, before, "tombstone 内数据必须完整")
        finally:
            os.chmod(settings.skill_root, 0o755)

    async def test_delete_purge_failure_is_explicit_and_diagnosable(self):
        sid = await self._create()
        try:
            async with self.Session() as db:
                with patch.object(svc, "_stage_skill_dir", self._stage_then_lock()):
                    with self.assertRaises(svc.SkillFilesystemError) as ctx:
                        await svc.delete_skill_lifecycle(db, sid)
            exc = ctx.exception
            self.assertEqual(exc.kind, svc.SkillFilesystemError.PURGE_FAILED)
            # 精确状态断言: DB 已删除 / canonical 已消失 / tombstone 仍存在
            self.assertEqual(await self._counts(sid), (0, 0), "DB 行必须已删除")
            self.assertFalse(self._canonical(sid).exists(), "canonical 目录必须已消失")
            tombs = self._tombstones()
            self.assertEqual(len(tombs), 1, "tombstone 必须仍存在")
            self.assertIn(tombs[0], str(exc),
                          "detail 必须携带 tombstone 路径(可诊断)")
            # 残留物不是 canonical 目录 → 不会被下一步代码误认为正常完整状态
            self.assertNotEqual(tombs[0], str(sid))
            self.assertTrue((Path(settings.skill_root) / tombs[0]).is_dir())
        finally:
            os.chmod(settings.skill_root, 0o755)

    # ---- update matrix -------------------------------------------------
    async def test_update_normal_persists_in_fresh_session(self):
        sid = await self._create()
        async with self.Session() as db:
            out = await svc.update_skill_metadata(
                db, sid, title="E4 新标题", description=None, actor_id=self.uid)
        self.assertEqual(out["title"], "E4 新标题")
        async with self.engine.connect() as conn:
            row = (await conn.execute(text(
                "SELECT title, description FROM community.skills WHERE id=:i"),
                {"i": sid})).fetchone()
        self.assertEqual(row[0], "E4 新标题")
        self.assertTrue(row[1], "未提供 description → coalesce 保持原值")

    async def test_update_commit_failure_no_half_update(self):
        sid = await self._create()
        async with self.engine.connect() as conn:
            old = (await conn.execute(text(
                "SELECT title, description FROM community.skills WHERE id=:i"),
                {"i": sid})).fetchone()
        async with self.Session() as real:
            db = _CommitFailSession(real)
            with self.assertRaises(RuntimeError) as ctx:
                await svc.update_skill_metadata(
                    db, sid, title="不该落库", description="也不该", actor_id=self.uid)
            self.assertEqual(str(ctx.exception), "E4 injected commit failure")

        async with self.engine.connect() as conn:
            now = (await conn.execute(text(
                "SELECT title, description FROM community.skills WHERE id=:i"),
                {"i": sid})).fetchone()
        self.assertEqual((now[0], now[1]), (old[0], old[1]),
                         "commit 失败后新会话必须看不到半更新")
        self.assertEqual(await self._counts(sid), (1, 3), "行与文件行不得被删除")

    async def test_update_validation_failure_zero_write(self):
        sid = await self._create()
        async with self.engine.connect() as conn:
            old = (await conn.execute(text(
                "SELECT title, updated_at FROM community.skills WHERE id=:i"),
                {"i": sid})).fetchone()
        async with self.Session() as db:
            with self.assertRaises(svc.SkillUpdateValidationError) as ctx:
                await svc.update_skill_metadata(
                    db, sid, title=None, description=None, actor_id=self.uid)
        self.assertEqual(str(ctx.exception), "没有可更新的字段")
        async with self.engine.connect() as conn:
            now = (await conn.execute(text(
                "SELECT title, updated_at FROM community.skills WHERE id=:i"),
                {"i": sid})).fetchone()
        self.assertEqual((now[0], now[1]), (old[0], old[1]), "校验失败不得写库")

    # ---- archive / file read domain ------------------------------------
    async def test_archive_normal_and_file_reads(self):
        sid = await self._create()
        async with self.Session() as db:
            payload = await svc.build_skill_archive(db, sid)
        with zipfile.ZipFile(io.BytesIO(payload)) as z:
            self.assertEqual(sorted(z.namelist()), sorted(FILES))
            self.assertEqual(z.read("SKILL.md"), SKILL_MD)
            self.assertEqual(z.read("assets/icon.png"), ICON_PNG)
            self.assertEqual(z.read(".gitignore"), GITIGNORE_TEXT)

        async with self.Session() as db:
            out = await svc.read_skill_file(db, sid, file_path="SKILL.md")
        self.assertEqual(out["content"], SKILL_MD.decode())
        self.assertEqual(out["size_bytes"], len(SKILL_MD))

        async with self.Session() as db:
            with self.assertRaises(svc.SkillFileNotFoundError) as ctx:
                await svc.read_skill_file(db, sid, file_path="assets/icon.png")
        self.assertEqual(str(ctx.exception), "二进制文件请通过 archive 端点获取 zip")

        async with self.Session() as db:
            with self.assertRaises(svc.SkillFileNotFoundError) as ctx:
                await svc.read_skill_file(db, sid, file_path="../../etc/passwd")
        self.assertEqual(str(ctx.exception), "文件不存在",
                         "manifest 未收录路径 → 404, 不做任何 FS 解析")

    async def test_archive_dir_missing_is_explicit_error(self):
        sid = await self._create()
        shutil.rmtree(self._canonical(sid))
        async with self.Session() as db:
            with self.assertRaises(svc.SkillArchiveUnavailableError) as ctx:
                await svc.build_skill_archive(db, sid)
        self.assertEqual(ctx.exception.kind,
                         svc.SkillArchiveUnavailableError.DIR_MISSING,
                         "目录缺失必须是可诊断的显式错误")
        self.assertIn(str(self._canonical(sid)), str(ctx.exception),
                      "detail 必须携带缺失的 canonical 路径")

    async def test_archive_manifest_file_missing_is_explicit_error(self):
        sid = await self._create()
        (self._canonical(sid) / "SKILL.md").unlink()
        async with self.Session() as db:
            with self.assertRaises(svc.SkillArchiveUnavailableError) as ctx:
                await svc.build_skill_archive(db, sid)
        self.assertEqual(ctx.exception.kind,
                         svc.SkillArchiveUnavailableError.FILE_MISSING)
        self.assertIn("SKILL.md", str(ctx.exception),
                      "detail 必须指出缺失的 manifest 路径")
