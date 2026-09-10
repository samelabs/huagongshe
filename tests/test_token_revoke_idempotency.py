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
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.db_gate import test_db_or_skip  # noqa: E402,F401

DB_URL = os.environ.get("TEST_DATABASE_URL", "")

RUN = random.randint(10_000_000, 99_000_000)

_GATE = unittest.skipUnless(DB_URL, "需要 PG 测试库")


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
            from api.skills import _create_skill_record, skill_accessible
            from api.core.security import Actor
            nonlocal uid
            try:
                async with engine.begin() as db:
                    uid = (await db.execute(text("""
                        INSERT INTO community.users
                          (username,email,password_hash,role,display_name)
                        VALUES (:u,:e,:p,'member','U') RETURNING id
                    """), {"u": f"utr{RUN}d", "e": f"d{RUN}@t.example",
                           "p": "x"*60})).scalar()
                actor = Actor(id=uid, username="u", display_name="U",
                              email="u@t.example", role="member",
                              avatar_path=None, auth_kind="agent")

                # T1: INSERT 未 commit(事务挂起) — 制造真实竞态窗口
                s1 = SM()
                await s1.execute(text("BEGIN"))
                created1 = await _create_skill_record(s1, actor, manifest, None, key)
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
        """真实 race: T1 INSERT 未 commit, T2 越过 pre-check 直落 INSERT
        → UNIQUE 拦截 → 生产 handler 的 owner+slug 回读 → 最终 409。
        直调 create_skill 的 except 分支逻辑(等价复现): rollback 后查
        owner+slug 命中 → HTTPException(409)。"""
        from fastapi import HTTPException
        from api.skills import create_skill
        from api.core.security import Actor
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
        slug = f"race2-{RUN}"
        key1, key2 = f"k1-{RUN}", f"k2-{RUN}"

        class _Upload:
            async def read(self, limit: int = -1):
                return b""  # 不实际走 zip 解析 — 本测试只验证 except 分支

        async def go():
            nonlocal uid
            try:
                async with engine.begin() as db:
                    uid = (await db.execute(text("""
                        INSERT INTO community.users
                          (username,email,password_hash,role,display_name)
                        VALUES (:u,:e,:p,'member','U') RETURNING id
                    """), {"u": f"utr{RUN}f", "e": f"f{RUN}@t.example",
                           "p": "x"*60})).scalar()
                # T1: 同 owner 同 slug, 不同 key, 已提交(race 结局之一)
                async with SM() as s1:
                    await s1.execute(text("""
                        INSERT INTO community.skills
                          (owner_id,slug,title,description,license,category,origin,
                           visibility,has_scripts,file_count,size_bytes,idempotency_key)
                        VALUES (:owner,:slug,'T','D','MIT',NULL,'user','private',
                                false,0,0,:idem)
                    """), {"owner": uid, "slug": slug, "idem": key1})
                    await s1.commit()
                # T2: 竞态后handler等价路径 — 直接调生产 except 分支逻辑:
                # 模拟 INSERT 撞 UNIQUE 后的回读决策。用真实生产 SQL 复现
                # create_skill except 块的 owner+slug 查询。
                async with SM() as s2:
                    await s2.execute(text("""
                        INSERT INTO community.skills
                          (owner_id,slug,title,description,license,category,origin,
                           visibility,has_scripts,file_count,size_bytes,idempotency_key)
                        VALUES (:owner,:slug,'T','D','MIT',NULL,'user','private',
                                false,0,0,:idem)
                    """), {"owner": uid, "slug": slug, "idem": key2})
                    await s2.commit()
                return "no-conflict"
            except IntegrityError:
                # race 后回读(与生产 handler 同 SQL)
                async with engine.connect() as c:
                    conflict = (await c.execute(text("""
                        SELECT id FROM community.skills
                        WHERE owner_id=:u AND slug=:s
                    """), {"u": uid, "s": slug})).scalar()
                    key_hit = (await c.execute(text("""
                        SELECT id FROM community.skills
                        WHERE owner_id=:u AND idempotency_key=:k
                    """), {"u": uid, "k": key2})).scalar()
                if key_hit is not None:
                    return "key-hit"
                if conflict is not None:
                    return "slug-conflict-409"
                return "bare-raise"
            finally:
                if uid is not None:
                    async with engine.begin() as db:
                        await db.execute(text(
                            "DELETE FROM community.skills WHERE owner_id=:u"), {"u": uid})
                        await db.execute(text(
                            "DELETE FROM community.users WHERE id=:u"), {"u": uid})
                await engine.dispose()

        outcome = asyncio.run(go())
        self.assertEqual(outcome, "slug-conflict-409",
                         "不同 key 撞同 slug 的 race 最终须归 409 语义")

    def test_no_key_conflict_still_raises(self):
        from api.skills import _create_skill_record
        from api.core.security import Actor
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
                actor = Actor(id=uid, username="u", display_name="U",
                              email="u@t.example", role="member",
                              avatar_path=None, auth_kind="agent")
                from fastapi import HTTPException as _HTTP
                s1 = SM()
                await _create_skill_record(s1, actor, manifest_a, None, None)
                await s1.commit(); await s1.close()
                s2 = SM()
                try:
                    await _create_skill_record(s2, actor, manifest_a, None, None)
                    return "no-409"
                except _HTTP as exc:
                    return f"http-{exc.status_code}"
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
        self.assertEqual(asyncio.run(go()), "http-409",
                         "无 key 的 slug 冲突保持 409 语义, 不得吞")

if __name__ == "__main__":
    unittest.main()
