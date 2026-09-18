"""Token revoke 语义归一 + secret 禁缓存 + skills race 收口 (2026-09-10)。

1. password change / admin disable 后用户 token 行物理不存在(不留 soft-revoke);
2. GET /users/me/tokens → Cache-Control: private, no-store;
3. skills 同 owner/同 key concurrent retry: 第二请求越过 pre-check 后
   INSERT 被 (owner_id, slug) UNIQUE 拦截 → IntegrityError 回滚回读,
   返回第一次创建的同一 skill;
4. 不同正常请求(slug 冲突无 key)仍 409 语义不被吞。

直调 endpoint 函数 + 真链 DB(test_hgs); 无 TestClient(避免跨 loop)。
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import random
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.db_gate import test_db_or_skip  # noqa: E402,F401

DB_URL = os.environ.get("TEST_DATABASE_URL", "")

RUN = random.randint(10_000_000, 99_000_000)

_GATE = unittest.skipUnless(DB_URL, "需要 PG 测试库")


def _skill_root_snapshot():
    """E7 §4 环境卫生: 记录测试前的 skill_root 目录集合。"""
    from api.core.config import settings
    root = Path(settings.skill_root)
    return root, (set(root.iterdir()) if root.is_dir() else set())


def _skill_root_cleanup(snap) -> None:
    """删掉本测试期间新建的 skill 目录(只动新增项, 不碰既有内容)。

    _create_skill_record 会 mkdir skill_root/<id>; 测试只回滚 DB 行,
    目录会留在盘上 → full suite 每轮残留。E7 定位 owner 后补此处清理。
    """
    root, before = snap
    if not root.is_dir():
        return
    for p in root.iterdir():
        if p not in before:
            shutil.rmtree(p, ignore_errors=True)


@_GATE
class TokenRevokeSemanticsTests(unittest.TestCase):
    def setUp(self):
        # change_password 走 enforce(redis) — discover 套跑下模块级 pool
        # 绑定已关闭 loop → 'Event loop is closed'。自建 pool 替换
        # (与 tests/test_resource_bounds.py 同修法)。
        import redis.asyncio as aioredis
        from api.core import rate_limit
        rate_limit.pool = aioredis.ConnectionPool.from_url(
            os.environ["HGS_REDIS_URL"], decode_responses=True)
        # E7 §4: 测试期间新建的 skill 目录出测试即清(环境卫生)
        self.addCleanup(_skill_root_cleanup, _skill_root_snapshot())

    def _engine(self):
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.pool import NullPool
        url = DB_URL.split("?")[0]
        if url.startswith("postgresql://"):
            url = "postgresql+asyncpg://" + url.split("://", 1)[1]
        return create_async_engine(url, poolclass=NullPool)

    def _sql(self):
        from sqlalchemy import text
        return text

    def _new_actor(self, uid: int, role: str = "member"):
        from api.core.security import Actor
        return Actor(id=uid, username=f"u{uid}", display_name="U",
                     email=f"u{uid}@t.example", role=role, avatar_path=None,
                     auth_kind="session")

    def test_password_change_deletes_tokens_physically(self):
        """change_password 后 user_api_tokens 行物理不存在。"""
        from api.users import change_password
        from api.core.security import password_hash
        from api.schemas.users import PasswordBody
        from sqlalchemy import text

        uid = None
        async def go():
            engine = self._engine()
            try:
                async with engine.begin() as db:
                    uid = (await db.execute(text("""
                        INSERT INTO community.users
                          (username,email,password_hash,role,display_name)
                        VALUES (:u,:e,:p,'member','U') RETURNING id
                    """), {"u": f"utr{RUN}a", "e": f"a{RUN}@t.example",
                           "p": await asyncio.to_thread(password_hash, "oldpass1A")})).scalar()
                    await db.execute(text("""
                        INSERT INTO community.user_api_tokens
                          (user_id,name,token_hash,token_prefix,token_plain)
                        VALUES (:uid,'t1',:h,'pfx12345678',:plain)
                    """), {"uid": uid,
                           "h": hashlib.sha256(("x"*43).encode()).digest(),
                           "plain": f"hgs_seed_{RUN}aaa"})
                actor = self._new_actor(uid)
                class _Resp:
                    headers: dict = {}
                    def delete_cookie(self, *a, **k): pass
                async with self._AsyncSessionFn(engine)() as session:
                    await change_password(
                        body=PasswordBody(current_password="oldpass1A",
                                          new_password="newpass2B",
                                          confirm_password="newpass2B"),
                        response=_Resp(), actor=actor, db=session)
                async with engine.connect() as c:
                    n = (await c.execute(text(
                        "SELECT count(*) FROM community.user_api_tokens WHERE user_id=:u"),
                        {"u": uid})).scalar()
                    n2 = (await c.execute(text(
                        "SELECT count(*) FROM community.sessions WHERE user_id=:u"),
                        {"u": uid})).scalar()
                return n, n2
            finally:
                if uid is not None:
                    async with engine.begin() as db:
                        await db.execute(text(
                            "DELETE FROM community.users WHERE id=:u"), {"u": uid})
                await engine.dispose()
        n_tok, n_sess = asyncio.run(go())
        self.assertEqual(n_tok, 0, "password change 后 token 行须物理删除")
        self.assertEqual(n_sess, 0, "sessions 同时清空")

    def test_admin_disable_deletes_tokens_physically(self):
        from api.admin import set_user_status
        from api.schemas.admin import UserStatusBody
        from api.core.security import Actor
        from sqlalchemy import text

        uid = None
        async def go():
            engine = self._engine()
            try:
                async with engine.begin() as db:
                    uid = (await db.execute(text("""
                        INSERT INTO community.users
                          (username,email,password_hash,role,display_name)
                        VALUES (:u,:e,:p,'member','U') RETURNING id
                    """), {"u": f"utr{RUN}b", "e": f"b{RUN}@t.example",
                           "p": "x"*60})).scalar()
                    await db.execute(text("""
                        INSERT INTO community.user_api_tokens
                          (user_id,name,token_hash,token_prefix,token_plain)
                        VALUES (:uid,'t1',:h,'pfx22345678',:plain)
                    """), {"uid": uid,
                           "h": hashlib.sha256(("y"*43).encode()).digest(),
                           "plain": f"hgs_seed_{RUN}bbb"})
                admin_actor = Actor(id=1, username="admin", display_name="A",
                                    email="adm@t.example", role="admin",
                                    avatar_path=None, auth_kind="session")
                async with self._AsyncSessionFn(engine)() as session:
                    await set_user_status(
                        user_id=uid, body=UserStatusBody(status="disabled"),
                        actor=admin_actor, db=session)
                async with engine.connect() as c:
                    n = (await c.execute(text(
                        "SELECT count(*) FROM community.user_api_tokens WHERE user_id=:u"),
                        {"u": uid})).scalar()
                return n
            finally:
                if uid is not None:
                    async with engine.begin() as db:
                        await db.execute(text(
                            "UPDATE community.users SET status='active' WHERE id=:u"), {"u": uid})
                        await db.execute(text(
                            "DELETE FROM community.users WHERE id=:u"), {"u": uid})
                await engine.dispose()
        n = asyncio.run(go())
        self.assertEqual(n, 0, "admin disable 后 token 行须物理删除")

    def test_list_tokens_no_store(self):
        from api.users import list_tokens
        from sqlalchemy import text

        uid = None
        async def go():
            engine = self._engine()
            try:
                async with engine.begin() as db:
                    uid = (await db.execute(text("""
                        INSERT INTO community.users
                          (username,email,password_hash,role,display_name)
                        VALUES (:u,:e,:p,'member','U') RETURNING id
                    """), {"u": f"utr{RUN}c", "e": f"c{RUN}@t.example",
                           "p": "x"*60})).scalar()
                class _Resp:
                    def __init__(self): self.headers = {}
                resp = _Resp()
                async with self._AsyncSessionFn(engine)() as session:
                    await list_tokens(response=resp, actor=self._new_actor(uid), db=session)
                return resp.headers.get("Cache-Control")
            finally:
                if uid is not None:
                    async with engine.begin() as db:
                        await db.execute(text(
                            "DELETE FROM community.users WHERE id=:u"), {"u": uid})
                await engine.dispose()
        cc = asyncio.run(go())
        self.assertEqual(cc, "private, no-store")

    def _AsyncSessionFn(self, engine):
        from sqlalchemy.ext.asyncio import AsyncSession
        from sqlalchemy.ext.asyncio import async_sessionmaker
        return async_sessionmaker(engine, expire_on_commit=False,
                                  class_=AsyncSession)


@_GATE
class SkillsRaceTests(unittest.TestCase):
    """同 owner/同 key/同 slug 的等价 race: 第二次 INSERT 被 slug UNIQUE 拦截
    → 回读第一次的 skill。用直调 _create_skill_record + 手工制造竞态窗口:
    第一个事务 INSERT 后未 commit 前第二个事务 INSERT → UniqueViolation。"""

    def setUp(self):
        # create_skill 走 enforce(redis) — 模块级 pool 绑定首个 loop,
        # 逐次 asyncio.run 关 loop → 'Event loop is closed'。
        # 自建 pool(与 TokenRevokeSemanticsTests 同修法)。
        import redis.asyncio as aioredis
        from api.core import rate_limit
        rate_limit.pool = aioredis.ConnectionPool.from_url(
            os.environ["HGS_REDIS_URL"], decode_responses=True)
        # E7 §4: 测试期间新建的 skill 目录出测试即清(环境卫生)
        self.addCleanup(_skill_root_cleanup, _skill_root_snapshot())

    def test_concurrent_same_key_returns_same_skill(self):
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

        url = DB_URL.split("?")[0]
        if url.startswith("postgresql://"):
            url = "postgresql+asyncpg://" + url.split("://", 1)[1]
        engine = create_async_engine(url, poolclass=__import__(
            "sqlalchemy.pool", fromlist=["NullPool"]).NullPool)
        SM = async_sessionmaker(engine, expire_on_commit=False)

        uid = None
        manifest = {
            "slug": f"race-{RUN}", "title": "T", "description": "D",
            "license": "MIT", "has_scripts": False, "file_count": 0,
            "size_bytes": 0, "files": [],
            "warnings": [],
        }
        key = f"race-key-{RUN}"

        async def go():
            from api.services.skills import _create_skill_record
            from api.services.skills import load_accessible_skill
            nonlocal uid
            try:
                async with engine.begin() as db:
                    uid = (await db.execute(text("""
                        INSERT INTO community.users
                          (username,email,password_hash,role,display_name)
                        VALUES (:u,:e,:p,'member','U') RETURNING id
                    """), {"u": f"utr{RUN}d", "e": f"d{RUN}@t.example",
                           "p": "x"*60})).scalar()
                # T1: INSERT 未 commit(事务挂起) — 制造真实竞态窗口
                s1 = SM()
                await s1.execute(text("BEGIN"))
                created1 = await _create_skill_record(s1, uid, manifest, None, key)
                # T2: 真实竞态=T2 事务的 pre-check 看不到 T1 未提交行,
                # 直落 INSERT → (owner_id, slug) UNIQUE 拦截。用与生产
                # _create_skill_record 相同的 INSERT 语句(无 pre-check)
                # 复现该窗口。
                from sqlalchemy.exc import IntegrityError
                s2 = SM()
                try:
                    await s2.execute(text("""
                        INSERT INTO community.skills
                          (owner_id,slug,title,description,license,category,origin,
                           visibility,has_scripts,file_count,size_bytes,idempotency_key)
                        VALUES (:owner,:slug,'T','D','MIT',NULL,'user','private',
                                false,0,0,:idem)
                    """), {"owner": uid, "slug": manifest["slug"], "idem": key})
                    await s2.commit()
                    created2 = "inserted"
                except IntegrityError:
                    await s2.rollback()
                    created2 = "unique_violation"
                await s1.commit()
                await s2.close()
                return created1["id"], created2
            finally:
                pass  # 清理在 readback 后统一执行(见下)
            return created1["id"], created2

        id1, outcome = asyncio.run(go())
        # 竞态事实: 第二个事务确实被 UNIQUE 拦截(而非也成功插入)
        self.assertEqual(outcome, "unique_violation",
                         "竞态窗口内第二 INSERT 应被 (owner,slug) UNIQUE 拦截")
        # 回读语义(与 create_skill 的 IntegrityError 分支同一 SQL):
        async def readback():
            async with engine.connect() as c:
                rows = (await c.execute(text("""
                    SELECT id FROM community.skills
                    WHERE owner_id=:u AND idempotency_key=:k
                """), {"u": uid, "k": key})).scalars().all()
            return rows
        async def cleanup():
            async with engine.begin() as db:
                await db.execute(text(
                    "DELETE FROM community.skills WHERE owner_id=:u"), {"u": uid})
                await db.execute(text(
                    "DELETE FROM community.users WHERE id=:u"), {"u": uid})
            await engine.dispose()

        rows = asyncio.run(readback())
        asyncio.run(cleanup())
        self.assertEqual(rows, [id1],
                         "按 (owner,key) 回读必须返回第一次创建的同一 skill")
        # 不同正常请求(slug 冲突、无 key)不被吞 → 仍 IntegrityError 上抛

    def test_concurrent_same_slug_different_key_ends_409(self):
        """真实调用 create_skill(): DB 预置同 owner/同 slug/different key,
        _create_skill_record 被替换为抛 IntegrityError(模拟 INSERT 被
        UNIQUE 拦截后的 race 终态) — 必须由生产 handler 完整走
        rollback → owner+key 未命中 → owner+slug 命中 → 409。"""
        from unittest import mock
        from fastapi import HTTPException
        from sqlalchemy import text
        from sqlalchemy.exc import IntegrityError
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
        from sqlalchemy.pool import NullPool
        from api.skills import create_skill
        from api.core.security import Actor

        url = DB_URL.split("?")[0]
        if url.startswith("postgresql://"):
            url = "postgresql+asyncpg://" + url.split("://", 1)[1]
        engine = create_async_engine(url, poolclass=NullPool)
        SM = async_sessionmaker(engine, expire_on_commit=False)
        uid = None
        slug = f"race2-{RUN}"
        key1, key2 = f"k1-{RUN}", f"k2-{RUN}"
        manifest = {"slug": slug, "title": "T", "description": "D",
                    "license": "MIT", "has_scripts": False, "file_count": 0,
                    "size_bytes": 0, "files": [], "warnings": []}

        class _Upload:
            async def read(self, limit: int = -1):
                return b""

        class _Settings:
            skill_zip_max_bytes = 1024 * 1024
            api_skill_write_limit_per_hour = 10_000

        async def _fake_create(db, actor, mf, cat, key):
            raise IntegrityError("race", None, Exception("unique"))

        def _fake_zip(raw):  # 生产侧 asyncio.to_thread 调用 → 必须同步
            return manifest

        async def go():
            nonlocal uid
            import api.services.skills as sk
            try:
                async with engine.begin() as db:
                    uid = (await db.execute(text("""
                        INSERT INTO community.users
                          (username,email,password_hash,role,display_name)
                        VALUES (:u,:e,:p,'member','U') RETURNING id
                    """), {"u": f"utr{RUN}f", "e": f"f{RUN}@t.example",
                           "p": "x"*60})).scalar()
                # 预置: 同 owner / 同 slug / key1(第一次请求已提交)
                async with SM() as s1:
                    await s1.execute(text("""
                        INSERT INTO community.skills
                          (owner_id,slug,title,description,license,category,origin,
                           visibility,has_scripts,file_count,size_bytes,idempotency_key)
                        VALUES (:owner,:slug,'T','D','MIT',NULL,'user','private',
                                false,0,0,:idem)
                    """), {"owner": uid, "slug": slug, "idem": key1})
                    await s1.commit()
                actor = Actor(id=uid, username="u", display_name="U",
                              email="u@t.example", role="member",
                              avatar_path=None, auth_kind="agent",
                              scopes=("skill:write",))
                session = SM()
                with mock.patch.object(sk, "_create_skill_record", _fake_create), \
                     mock.patch.object(sk, "extract_skill_zip", _fake_zip), \
                     mock.patch.object(sk, "settings", _Settings()):
                    try:
                        await create_skill(file=_Upload(), category=None,
                                           request_idempotency_key=key2,
                                           actor=actor, db=session)
                        return "no-exception"
                    except HTTPException as exc:
                        return f"http-{exc.status_code}"
                    finally:
                        await session.close()
            finally:
                if uid is not None:
                    async with engine.begin() as db:
                        await db.execute(text(
                            "DELETE FROM community.skills WHERE owner_id=:u"), {"u": uid})
                        await db.execute(text(
                            "DELETE FROM community.users WHERE id=:u"), {"u": uid})
                await engine.dispose()

        outcome = asyncio.run(go())
        self.assertEqual(outcome, "http-409",
                         "different key 撞同 slug 须由真实 handler 抛 409")

    def test_same_key_retry_returns_existing_skill_via_create_skill(self):
        """same-key retry: pre-check(owner+key) 命中直接返回既有 skill —
        走真实 create_skill + 真实 _create_skill_record 未被调用断言。"""
        from unittest import mock
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
        from sqlalchemy.pool import NullPool
        from api.skills import create_skill
        from api.core.security import Actor

        url = DB_URL.split("?")[0]
        if url.startswith("postgresql://"):
            url = "postgresql+asyncpg://" + url.split("://", 1)[1]
        engine = create_async_engine(url, poolclass=NullPool)
        SM = async_sessionmaker(engine, expire_on_commit=False)
        uid = None
        slug = f"race3-{RUN}"
        key = f"kk-{RUN}"
        manifest = {"slug": slug, "title": "T", "description": "D",
                    "license": "MIT", "has_scripts": False, "file_count": 0,
                    "size_bytes": 0, "files": [], "warnings": []}

        class _Upload:
            async def read(self, limit: int = -1):
                return b""

        class _Settings:
            skill_zip_max_bytes = 1024 * 1024
            api_skill_write_limit_per_hour = 10_000

        async def _fake_create(db, actor, mf, cat, k):
            raise AssertionError("pre-check 命中后不得再走 INSERT")

        def _fake_zip(raw):  # 生产侧 asyncio.to_thread 调用 → 必须同步
            return manifest

        async def go():
            nonlocal uid
            import api.services.skills as sk
            try:
                async with engine.begin() as db:
                    uid = (await db.execute(text("""
                        INSERT INTO community.users
                          (username,email,password_hash,role,display_name)
                        VALUES (:u,:e,:p,'member','U') RETURNING id
                    """), {"u": f"utr{RUN}g", "e": f"g{RUN}@t.example",
                           "p": "x"*60})).scalar()
                async with SM() as s1:
                    sid = (await s1.execute(text("""
                        INSERT INTO community.skills
                          (owner_id,slug,title,description,license,category,origin,
                           visibility,has_scripts,file_count,size_bytes,idempotency_key)
                        VALUES (:owner,:slug,'T','D','MIT',NULL,'user','private',
                                false,0,0,:idem) RETURNING id
                    """), {"owner": uid, "slug": slug, "idem": key})).scalar()
                    await s1.commit()
                actor = Actor(id=uid, username="u", display_name="U",
                              email="u@t.example", role="member",
                              avatar_path=None, auth_kind="agent",
                              scopes=("skill:write",))
                session = SM()
                with mock.patch.object(sk, "_create_skill_record", _fake_create), \
                     mock.patch.object(sk, "extract_skill_zip", _fake_zip), \
                     mock.patch.object(sk, "settings", _Settings()):
                    out = await create_skill(file=_Upload(), category=None,
                                             request_idempotency_key=key,
                                             actor=actor, db=session)
                await session.close()
                return out["id"], sid
            finally:
                if uid is not None:
                    async with engine.begin() as db:
                        await db.execute(text(
                            "DELETE FROM community.skills WHERE owner_id=:u"), {"u": uid})
                        await db.execute(text(
                            "DELETE FROM community.users WHERE id=:u"), {"u": uid})
                await engine.dispose()

        got, existing = asyncio.run(go())
        self.assertEqual(got, existing,
                         "same-key retry 必须返回既有 skill(pre-check 命中)")

    def test_unrelated_integrity_error_reraises_via_create_skill(self):
        """unrelated IntegrityError: key/slug 均未命中 → 原异常继续 raise。"""
        from unittest import mock
        from sqlalchemy import text
        from sqlalchemy.exc import IntegrityError
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
        from sqlalchemy.pool import NullPool
        from api.skills import create_skill
        from api.core.security import Actor

        url = DB_URL.split("?")[0]
        if url.startswith("postgresql://"):
            url = "postgresql+asyncpg://" + url.split("://", 1)[1]
        engine = create_async_engine(url, poolclass=NullPool)
        SM = async_sessionmaker(engine, expire_on_commit=False)
        uid = None
        slug = f"race4-{RUN}"  # DB 无此 slug → slug 回读不命中
        key = f"kk4-{RUN}"    # DB 无此 key
        manifest = {"slug": slug, "title": "T", "description": "D",
                    "license": "MIT", "has_scripts": False, "file_count": 0,
                    "size_bytes": 0, "files": [], "warnings": []}

        class _Upload:
            async def read(self, limit: int = -1):
                return b""

        class _Settings:
            skill_zip_max_bytes = 1024 * 1024
            api_skill_write_limit_per_hour = 10_000

        async def _fake_create(db, actor, mf, cat, k):
            raise IntegrityError("unrelated", None, Exception("fk"))

        def _fake_zip(raw):  # 生产侧 asyncio.to_thread 调用 → 必须同步
            return manifest

        async def go():
            nonlocal uid
            import api.services.skills as sk
            try:
                async with engine.begin() as db:
                    uid = (await db.execute(text("""
                        INSERT INTO community.users
                          (username,email,password_hash,role,display_name)
                        VALUES (:u,:e,:p,'member','U') RETURNING id
                    """), {"u": f"utr{RUN}h", "e": f"h{RUN}@t.example",
                           "p": "x"*60})).scalar()
                actor = Actor(id=uid, username="u", display_name="U",
                              email="u@t.example", role="member",
                              avatar_path=None, auth_kind="agent",
                              scopes=("skill:write",))
                session = SM()
                with mock.patch.object(sk, "_create_skill_record", _fake_create), \
                     mock.patch.object(sk, "extract_skill_zip", _fake_zip), \
                     mock.patch.object(sk, "settings", _Settings()):
                    try:
                        await create_skill(file=_Upload(), category=None,
                                           request_idempotency_key=key,
                                           actor=actor, db=session)
                        return "no-exception"
                    except IntegrityError:
                        return "reraw"
                    finally:
                        await session.close()
            finally:
                if uid is not None:
                    async with engine.begin() as db:
                        await db.execute(text(
                            "DELETE FROM community.skills WHERE owner_id=:u"), {"u": uid})
                        await db.execute(text(
                            "DELETE FROM community.users WHERE id=:u"), {"u": uid})
                await engine.dispose()

        self.assertEqual(asyncio.run(go()), "reraw",
                         "不相关 IntegrityError 不得被吞成 409/其他")

    def test_no_key_conflict_still_raises(self):
        from api.services.skills import _create_skill_record, SkillSlugConflictError
        from sqlalchemy import text
        from sqlalchemy.exc import IntegrityError
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
        from sqlalchemy.pool import NullPool

        url = DB_URL.split("?")[0]
        if url.startswith("postgresql://"):
            url = "postgresql+asyncpg://" + url.split("://", 1)[1]
        engine = create_async_engine(url, poolclass=NullPool)
        SM = async_sessionmaker(engine, expire_on_commit=False)
        uid = None
        manifest_a = {"slug": f"nk-{RUN}", "title": "T", "description": "D",
                      "license": "MIT", "has_scripts": False, "file_count": 0,
                      "size_bytes": 0, "files": [], "warnings": []}
        async def go():
            nonlocal uid
            try:
                async with engine.begin() as db:
                    uid = (await db.execute(text("""
                        INSERT INTO community.users
                          (username,email,password_hash,role,display_name)
                        VALUES (:u,:e,:p,'member','U') RETURNING id
                    """), {"u": f"utr{RUN}e", "e": f"e{RUN}@t.example",
                           "p": "x"*60})).scalar()
                s1 = SM()
                await _create_skill_record(s1, uid, manifest_a, None, None)
                await s1.commit(); await s1.close()
                s2 = SM()
                try:
                    await _create_skill_record(s2, uid, manifest_a, None, None)
                    return "no-conflict"
                except SkillSlugConflictError as exc:
                    # G3.1D: canonical owner 抛 neutral error(同一 409 文案);
                    # HTTP 409 映射由 tests/test_skill_create_service.py 覆盖。
                    return f"slug-conflict:{exc.detail}"
                except IntegrityError:
                    return "raised"
                finally:
                    await s2.close()
            finally:
                if uid is not None:
                    async with engine.begin() as db:
                        await db.execute(text(
                            "DELETE FROM community.skills WHERE owner_id=:u"), {"u": uid})
                        await db.execute(text(
                            "DELETE FROM community.users WHERE id=:u"), {"u": uid})
                await engine.dispose()
        self.assertEqual(
            asyncio.run(go()),
            f"slug-conflict:已存在同名技能（slug=nk-{RUN}），请先删除或改名",
            "无 key 的 slug 冲突保持原 409 语义(文案逐字), 不得吞")

if __name__ == "__main__":
    unittest.main()
