"""AI Key 明文契约。

token_plain 列有意存在、明文有意落库（撤销 「明文不落库」收口）：
1. DB 列存在且带注释（information_schema + pg_description 断言）；
2. 新建 Key 落库明文：token_plain = 明文，token_hash = sha256(明文)；
3. 本人网页会话的 GET /users/me/tokens 取回明文（token 字段，no-store）；
4. AI Key（agent）与匿名调用拿不到：REST 对 agent 一律 401，匿名 401；
5. 无明文的旧 Key（drop 期间创建或历史行）列表返回 null；
6. 鉴权不受明文恢复影响：按 token_hash 解析存量 Key 继续有效；
7. users.email_verified_at 预留列存在且带「项目负责人决定保留」注释
   。

理由：每账号最多 5 个有效 Key，本人可在设置页再次查看、复制，降低
使用摩擦。禁止以安全为由删除本列或停止写入/回传 —— 变更须经项目负责人
确认。明文只在设置页给本人：MCP、日志、错误信息不得出现。

直调 endpoint 函数 + 真链 DB(test_hgs)；无 TestClient(避免跨 loop)。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import secrets
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.db_gate import test_db_or_skip  # noqa: E402

# 建任何 engine 之前先过测试库闸(库名模式 + sentinel 双保险)。
DB_URL = test_db_or_skip()

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


async def _make_user(engine, tag: str) -> int:
    from sqlalchemy import text
    async with engine.begin() as db:
        return int((await db.execute(text("""
            INSERT INTO community.users
              (username,email,password_hash,role,display_name)
            VALUES (:u,:e,:p,'member','U') RETURNING id
        """), {"u": f"utp{RUN}{tag}", "e": f"p{RUN}{tag}@t.example",
               "p": "x" * 60})).scalar())


async def _cleanup_user(engine, uid: int) -> None:
    from sqlalchemy import text
    async with engine.begin() as db:
        await db.execute(text(
            "DELETE FROM community.user_api_tokens WHERE user_id=:u"), {"u": uid})
        await db.execute(text(
            "DELETE FROM community.sessions WHERE user_id=:u"), {"u": uid})
        await db.execute(text(
            "DELETE FROM community.users WHERE id=:u"), {"u": uid})


@_GATE
class TokenPlaintextContractTests(unittest.TestCase):
    def test_token_plain_column_exists_with_ruling_comment(self):
        """20261014_02 之后 token_plain 列存在, 且带注释。"""
        from sqlalchemy import text

        async def go():
            engine = _engine()
            try:
                async with engine.connect() as c:
                    rows = (await c.execute(text("""
                        SELECT column_name,
                               col_description('community.user_api_tokens'::regclass,
                                               dtd_identifier::int)
                        FROM information_schema.columns
                        WHERE table_schema='community'
                          AND table_name='user_api_tokens'
                          AND column_name='token_plain'
                    """))).first()
                    all_cols = (await c.execute(text("""
                        SELECT column_name FROM information_schema.columns
                        WHERE table_schema='community' AND table_name='user_api_tokens'
                    """))).scalars().all()
                return rows, all_cols
            finally:
                await engine.dispose()

        row, columns = asyncio.run(go())
        self.assertIsNotNone(row, "token_plain 列必须存在（migration 20261014_02）")
        comment = (row[1] or "")
        for phrase in ("明文", "有意", "项目负责人", "再次查看"):
            self.assertIn(phrase, comment,
                          f"列注释必须写明该决策（缺「{phrase}」）: {comment!r}")
        for required in ("id", "user_id", "name", "token_hash", "token_prefix"):
            self.assertIn(required, columns, f"鉴权依赖列 {required} 必须仍在")

    def test_email_verified_at_column_has_reserved_comment(self):
        """users.email_verified_at 预留列存在, 且带「项目负责人决定保留」注释。"""
        from sqlalchemy import text

        async def go():
            engine = _engine()
            try:
                async with engine.connect() as c:
                    return (await c.execute(text("""
                        SELECT column_name,
                               col_description('community.users'::regclass,
                                               dtd_identifier::int)
                        FROM information_schema.columns
                        WHERE table_schema='community'
                          AND table_name='users'
                          AND column_name='email_verified_at'
                    """))).first()
            finally:
                await engine.dispose()

        row = asyncio.run(go())
        self.assertIsNotNone(row, "email_verified_at 列必须存在（预留字段）")
        comment = (row[1] or "")
        for phrase in ("预留", "邮箱验证", "项目负责人"):
            self.assertIn(phrase, comment,
                          f"列注释必须写明预留决策（缺「{phrase}」）: {comment!r}")

    def test_create_stores_plaintext_in_db(self):
        """新建 Key: 201 响应返回明文, 且落库行 token_plain 即该明文。"""
        from api.users import create_token
        from api.schemas.users import TokenBody
        from sqlalchemy import text

        uid = None
        async def go():
            engine = _engine()
            try:
                uid = await _make_user(engine, "a")
                async with _session_fn(engine)() as session:
                    body = TokenBody(name="contract", expires_in_days=30)
                    created = await create_token(body=body, actor=_actor(uid),
                                                 db=session)
                async with engine.connect() as c:
                    row = (await c.execute(text("""
                        SELECT token_hash, token_prefix, token_plain
                        FROM community.user_api_tokens
                        WHERE user_id=:u AND name='contract'
                    """), {"u": uid})).fetchone()
                return created, row
            finally:
                if uid is not None:
                    await _cleanup_user(engine, uid)

        created, row = asyncio.run(go())
        plain = created.get("token") or ""
        self.assertTrue(plain.startswith("hgs_"), "创建响应必须含明文 credential")
        self.assertIsNotNone(row)
        self.assertEqual(row[2], plain, "落库行 token_plain 必须就是明文（有意保存）")
        self.assertEqual(row[1], plain[:12], "token_prefix = 明文前 12 位")
        self.assertEqual(row[0], hashlib.sha256(plain.encode()).digest(),
                         "token_hash = sha256(明文)")

    def test_list_returns_plaintext_to_session_owner(self):
        """本人网页会话的列表能取回明文, 响应禁缓存。"""
        from api.users import create_token, list_tokens
        from api.schemas.users import TokenBody

        uid = None
        async def go():
            engine = _engine()
            try:
                uid = await _make_user(engine, "b")
                actor = _actor(uid)
                async with _session_fn(engine)() as session:
                    created = await create_token(
                        body=TokenBody(name="list-contract", expires_in_days=None),
                        actor=actor, db=session)
                    resp = _Resp()
                    items = await list_tokens(response=resp, actor=actor, db=session)
                return created.get("token") or "", items, resp.headers
            finally:
                if uid is not None:
                    await _cleanup_user(engine, uid)

        plain, items, headers = asyncio.run(go())
        self.assertEqual(headers.get("Cache-Control"), "private, no-store",
                         "明文列表必须禁缓存")
        self.assertTrue(items, "列表至少含刚建的 Key")
        item = items[0]
        self.assertIn("token", item, "列表必须含 token（明文）字段")
        self.assertEqual(item["token"], plain, "列表取回的必须是落库明文")
        self.assertIn("token_prefix", item, "列表保留前缀元数据")
        self.assertIn("last_used_at", item, "列表保留时间元数据")

    def test_list_unreachable_for_agent_and_anonymous(self):
        """AI Key 与匿名都拿不到列表: REST 对 agent 一律 401, 匿名 401。"""
        from fastapi import HTTPException
        from api.core.security import optional_actor, current_actor
        from sqlalchemy import text

        uid = None
        # 长度须 ≥32: resolve_actor 对过短 Bearer 一律不认(认证层规则)
        token = f"hgs_contract_{secrets.token_urlsafe(24)}"
        async def go():
            engine = _engine()
            try:
                uid = await _make_user(engine, "c")
                async with engine.begin() as db:
                    await db.execute(text("""
                        INSERT INTO community.user_api_tokens
                          (user_id,name,token_hash,token_prefix,token_plain)
                        VALUES (:uid,'agent-probe',:h,:pfx,:plain)
                    """), {"uid": uid,
                           "h": hashlib.sha256(token.encode()).digest(),
                           "pfx": token[:12], "plain": token})
                async with _session_fn(engine)() as session:
                    agent_exc = anon_exc = None
                    try:
                        await optional_actor(
                            db=session, authorization=f"Bearer {token}",
                            session_token=None)
                    except HTTPException as exc:
                        agent_exc = exc
                    try:
                        await current_actor(actor=await optional_actor(
                            db=session, authorization=None, session_token=None))
                    except HTTPException as exc:
                        anon_exc = exc
                    return agent_exc, anon_exc
            finally:
                if uid is not None:
                    await _cleanup_user(engine, uid)

        agent_exc, anon_exc = asyncio.run(go())
        self.assertIsNotNone(agent_exc, "AI Key 调 REST 必须被依赖层拒绝")
        self.assertEqual(agent_exc.status_code, 401)
        self.assertEqual(agent_exc.detail.get("kind"), "rest_agent_forbidden")
        self.assertIsNotNone(anon_exc, "匿名调用必须被拒绝")
        self.assertEqual(anon_exc.status_code, 401)

    def test_legacy_key_without_plaintext_returns_null(self):
        """无明文的旧 Key（drop 期间/历史行）: 列表 token 返回 null, 不报错。"""
        from api.users import list_tokens
        from sqlalchemy import text

        uid = None
        async def go():
            engine = _engine()
            try:
                uid = await _make_user(engine, "d")
                async with engine.begin() as db:
                    await db.execute(text("""
                        INSERT INTO community.user_api_tokens
                          (user_id,name,token_hash,token_prefix)
                        VALUES (:uid,'legacy',:h,:pfx)
                    """), {"uid": uid,
                           "h": hashlib.sha256(b"legacy-no-plain").digest(),
                           "pfx": "hgs_legacy"})
                async with _session_fn(engine)() as session:
                    resp = _Resp()
                    items = await list_tokens(response=resp, actor=_actor(uid),
                                              db=session)
                return items
            finally:
                if uid is not None:
                    await _cleanup_user(engine, uid)

        items = asyncio.run(go())
        self.assertEqual(len(items), 1)
        self.assertIn("token", items[0])
        self.assertIsNone(items[0]["token"], "无明文的旧 Key 必须返回 null")

    def test_bearer_auth_still_resolves_by_hash(self):
        """存量 Key 继续有效: sha256(明文) 鉴权路径不受明文恢复影响。"""
        from api.core.security import resolve_actor
        from sqlalchemy import text

        uid = None
        # 长度须 ≥32: resolve_actor 对过短 Bearer 一律不认(认证层规则)
        token = f"hgs_contract_{secrets.token_urlsafe(24)}"
        async def go():
            engine = _engine()
            try:
                uid = await _make_user(engine, "e")
                async with engine.begin() as db:
                    await db.execute(text("""
                        INSERT INTO community.user_api_tokens
                          (user_id,name,token_hash,token_prefix)
                        VALUES (:uid,'bearer',:h,:pfx)
                    """), {"uid": uid,
                           "h": hashlib.sha256(token.encode()).digest(),
                           "pfx": token[:12]})
                async with _session_fn(engine)() as session:
                    actor = await resolve_actor(
                        session, f"Bearer {token}", session_token=None)
                # uid 一并返回: go() 内的赋值是局部变量, 外层拿不到
                return uid, (actor.id if actor else None), (actor.auth_kind if actor else None)
            finally:
                if uid is not None:
                    await _cleanup_user(engine, uid)

        uid, got, kind = asyncio.run(go())
        self.assertEqual(got, uid, "按 token_hash 鉴权的存量 Key 必须继续有效")
        self.assertEqual(kind, "agent")

    def test_plaintext_never_serialized_elsewhere(self):
        """防御性抽查: 明文不出现在 list 响应之外的错误/日志通道由边界注释
        与 401 依赖层保证; 这里锁 list 响应可 JSON 序列化且明文仅出现在
        token 字段（防止未来顺手把 token_plain 原字段名也带出去）。"""
        from api.users import create_token, list_tokens
        from api.schemas.users import TokenBody

        uid = None
        async def go():
            engine = _engine()
            try:
                uid = await _make_user(engine, "f")
                actor = _actor(uid)
                async with _session_fn(engine)() as session:
                    created = await create_token(
                        body=TokenBody(name="shape", expires_in_days=None),
                        actor=actor, db=session)
                    resp = _Resp()
                    items = await list_tokens(response=resp, actor=actor, db=session)
                return created.get("token") or "", items
            finally:
                if uid is not None:
                    await _cleanup_user(engine, uid)

        plain, items = asyncio.run(go())
        serialized = json.dumps(items, ensure_ascii=False, default=str)
        self.assertNotIn("token_plain", items[0], "对外字段名是 token, 不回传列名 token_plain")
        self.assertEqual(serialized.count(plain), 1, "列表里明文只出现在 token 字段一次")


if __name__ == "__main__":
    unittest.main()
