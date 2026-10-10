"""AI Key 明文契约（2026-10-11 v1.7 收口，20261011_01 migration）。

token_plain 列已删除、明文不落库：
1. DB 列不存在（information_schema 断言，baseline 已同步）；
2. POST /users/me/tokens 201 响应里明文只出现一次（token 字段），落库行无明文；
3. GET /users/me/tokens 列表响应不含任何明文字段，也不含已建 Key 的明文；
4. 按哈希鉴权不受影响：同一明文 Bearer 仍解析为同一用户（存量 Key 继续有效）。

直调 endpoint 函数 + 真链 DB(test_hgs)；无 TestClient(避免跨 loop)。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
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


def _engine():
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool
    url = DB_URL.split("?")[0]
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url.split("://", 1)[1]
    return create_async_engine(url, poolclass=NullPool)


def _session_fn(engine):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def _actor(uid: int):
    from api.core.security import Actor
    return Actor(id=uid, username=f"u{uid}", display_name="U",
                 email=f"u{uid}@t.example", role="member", avatar_path=None,
                 auth_kind="session")


class _Resp:
    def __init__(self):
        self.headers = {}


@_GATE
class TokenPlaintextContractTests(unittest.TestCase):
    def test_token_plain_column_is_gone(self):
        """20261011_01 之后 community.user_api_tokens 不再有 token_plain 列。"""
        from sqlalchemy import text

        async def go():
            engine = _engine()
            try:
                async with engine.connect() as c:
                    rows = (await c.execute(text("""
                        SELECT column_name FROM information_schema.columns
                        WHERE table_schema='community' AND table_name='user_api_tokens'
                    """))).scalars().all()
                return rows
            finally:
                await engine.dispose()

        columns = asyncio.run(go())
        self.assertNotIn("token_plain", columns,
                         "token_plain 列必须已删除（migration 20261011_01）")
        for required in ("id", "user_id", "name", "token_hash", "token_prefix"):
            self.assertIn(required, columns, f"鉴权依赖列 {required} 必须仍在")

    def test_create_returns_plaintext_once_and_stores_none(self):
        """201 响应里明文只出现一次；DB 里没有明文副本。"""
        from api.users import create_token
        from api.schemas.users import TokenBody
        from sqlalchemy import text

        uid = None
        async def go():
            engine = _engine()
            try:
                async with engine.begin() as db:
                    uid = (await db.execute(text("""
                        INSERT INTO community.users
                          (username,email,password_hash,role,display_name)
                        VALUES (:u,:e,:p,'member','U') RETURNING id
                    """), {"u": f"utp{RUN}a", "e": f"pa{RUN}@t.example",
                           "p": "x"*60})).scalar()
                async with _session_fn(engine)() as session:
                    body = TokenBody(name="contract", expires_in_days=30)
                    created = await create_token(body=body, actor=_actor(uid),
                                                 db=session)
                async with engine.connect() as c:
                    row = (await c.execute(text("""
                        SELECT token_hash, token_prefix
                        FROM community.user_api_tokens
                        WHERE user_id=:u AND name='contract'
                    """), {"u": uid})).fetchone()
                return created, row
            finally:
                if uid is not None:
                    async with engine.begin() as db:
                        await db.execute(text(
                            "DELETE FROM community.user_api_tokens WHERE user_id=:u"),
                            {"u": uid})
                        await db.execute(text(
                            "DELETE FROM community.users WHERE id=:u"), {"u": uid})
                await engine.dispose()

        created, row = asyncio.run(go())
        plain = created.get("token") or ""
        self.assertTrue(plain.startswith("hgs_"), "创建响应必须含一次明文 credential")
        # 明文只在 token 字段出现一次: 序列化整个响应计数
        serialized = json.dumps(created, ensure_ascii=False, default=str)
        self.assertEqual(serialized.count(plain), 1,
                         "明文在整个创建响应里只允许出现一次")
        self.assertNotIn("token_plain", created, "不得再回传 token_plain 字段")
        # 落库行: hash/前缀对得上, 无明文可对(列已不存在, test_token_plain_column_is_gone 覆盖)
        self.assertIsNotNone(row)
        self.assertEqual(row[1], plain[:12], "token_prefix = 明文前 12 位")
        self.assertEqual(row[0], hashlib.sha256(plain.encode()).digest(),
                         "token_hash = sha256(明文)")

    def test_list_tokens_has_no_plaintext(self):
        """列表响应无任何明文字段，也不泄露已建 Key 的明文。"""
        from api.users import create_token, list_tokens
        from api.schemas.users import TokenBody
        from sqlalchemy import text

        uid = None
        async def go():
            engine = _engine()
            try:
                async with engine.begin() as db:
                    uid = (await db.execute(text("""
                        INSERT INTO community.users
                          (username,email,password_hash,role,display_name)
                        VALUES (:u,:e,:p,'member','U') RETURNING id
                    """), {"u": f"utp{RUN}b", "e": f"pb{RUN}@t.example",
                           "p": "x"*60})).scalar()
                actor = _actor(uid)
                async with _session_fn(engine)() as session:
                    created = await create_token(
                        body=TokenBody(name="list-contract", expires_in_days=None),
                        actor=actor, db=session)
                    resp = _Resp()
                    items = await list_tokens(response=resp, actor=actor, db=session)
                return created.get("token") or "", items
            finally:
                if uid is not None:
                    async with engine.begin() as db:
                        await db.execute(text(
                            "DELETE FROM community.user_api_tokens WHERE user_id=:u"),
                            {"u": uid})
                        await db.execute(text(
                            "DELETE FROM community.users WHERE id=:u"), {"u": uid})
                await engine.dispose()

        plain, items = asyncio.run(go())
        serialized = json.dumps(items, ensure_ascii=False, default=str)
        self.assertNotIn("token_plain", serialized, "列表不得含 token_plain 字段")
        self.assertNotIn(plain, serialized, "列表不得泄露已建 Key 的明文")
        self.assertNotIn("token", items[0], "列表不得含 token credential 字段")
        self.assertIn("token_prefix", items[0], "列表保留前缀元数据")
        self.assertIn("last_used_at", items[0], "列表保留时间元数据")

    def test_bearer_auth_still_resolves_by_hash(self):
        """存量 Key 继续有效: sha256(明文) 鉴权路径不受列删除影响。"""
        from api.core.security import resolve_actor
        from sqlalchemy import text

        uid = None
        token = f"hgs_contract_{RUN}_{RUN}"
        async def go():
            engine = _engine()
            try:
                async with engine.begin() as db:
                    uid = (await db.execute(text("""
                        INSERT INTO community.users
                          (username,email,password_hash,role,display_name)
                        VALUES (:u,:e,:p,'member','U') RETURNING id
                    """), {"u": f"utp{RUN}c", "e": f"pc{RUN}@t.example",
                           "p": "x"*60})).scalar()
                    await db.execute(text("""
                        INSERT INTO community.user_api_tokens
                          (user_id,name,token_hash,token_prefix)
                        VALUES (:uid,'bearer',:h,:pfx)
                    """), {"uid": uid,
                           "h": hashlib.sha256(token.encode()).digest(),
                           "pfx": token[:12]})
                async with _session_fn(engine)() as session:
                    actor = await resolve_actor(
                        db, f"Bearer {token}", session_token=None)
                return (actor.id if actor else None)
            finally:
                if uid is not None:
                    async with engine.begin() as db:
                        await db.execute(text(
                            "DELETE FROM community.user_api_tokens WHERE user_id=:u"),
                            {"u": uid})
                        await db.execute(text(
                            "DELETE FROM community.users WHERE id=:u"), {"u": uid})
                await engine.dispose()

        got = asyncio.run(go())
        self.assertEqual(got, uid, "按 token_hash 鉴权的存量 Key 必须继续有效")


if __name__ == "__main__":
    unittest.main()
