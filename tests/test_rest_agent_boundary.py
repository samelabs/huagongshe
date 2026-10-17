"""v1.7.1 — REST 收为网站内部面 + 错误码化, 针对性测试。

1. optional_actor 依赖: AI Key(agent)对任意 REST 路由 401(kind=
   rest_agent_forbidden); 会话 cookie 与匿名行为不变;
2. 治理锁: api/ 用户面(web)不再出现裸中文 detail 的 HTTPException;
3. 搜索入口: CAS 校验位错误 → 400 {"message","kind":"invalid_cas"};
   registry/路由表不再有 agent-guide / AGENT_HTTP 投影(治理测试另有专锁,
   此处函数级复核 optional_actor 拦截点本身)。
"""
from __future__ import annotations

import ast
import os
import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tests.db_gate import require_test_db  # 统一测试库闸
try:
    DB_URL = require_test_db().split("?", 1)[0]
except Exception:
    DB_URL = ""
_GATE = unittest.skipUnless(DB_URL, "需要 PG 测试库 (TEST_DATABASE_URL 过闸)")

CJK_RE = re.compile(r"[\u3400-\u9fff\u3000-\u303f\uff00-\uffef]")
# 内部面: 管理端(admin)与 worker 协议(workapi)的错误消费者是管理员页面与
# worker 代码, 不在本轮"用户可见业务错误"范围; OAuth 协议错误走标准
# error/error_description JSONResponse, 不是 HTTPException 中文 detail。
EXCLUDED_FILES = {"admin.py", "workapi.py", "oauth.py"}
WEB_API_FILES = sorted(
    p for p in (REPO / "api").rglob("*.py")
    if p.name not in EXCLUDED_FILES and "__pycache__" not in p.parts
)


class NoBareChineseDetailTests(unittest.TestCase):
    """治理锁: 用户面 HTTPException 的 detail 必须是 {message, kind} 结构。

    静态 AST 扫描: detail 为含 CJK 的字符串常量(或 f-string 恒定段含 CJK)
    即违规 —— 新代码不得回退到裸中文 detail。
    """

    def _bare_chinese_details(self):
        findings = []
        for path in WEB_API_FILES:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if not (isinstance(func, ast.Name) and func.id == "HTTPException"):
                    continue
                for kw in node.keywords:
                    if kw.arg not in ("detail", None):
                        continue
                    value = kw.value
                    texts = []
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        texts = [value.value]
                    elif isinstance(value, ast.JoinedStr):
                        texts = [
                            part.value for part in value.values
                            if isinstance(part, ast.Constant)
                            and isinstance(part.value, str)
                        ]
                    for text in texts:
                        if CJK_RE.search(text):
                            findings.append(
                                f"{path.relative_to(REPO)}:{node.lineno} {text[:40]}")
        return findings

    def test_web_api_has_no_bare_chinese_exception_detail(self):
        findings = self._bare_chinese_details()
        self.assertEqual(
            findings, [],
            "用户面 HTTPException 不得用裸中文 detail, 须为 "
            '{"message": <中文原文>, "kind": <snake_case>}:\n' + "\n".join(findings))


@_GATE
class OptionalActorRejectsAgentTests(unittest.TestCase):
    """REST 依赖层: AI Key 一律 401; 会话/匿名不变(真链测试库)。"""

    def run_coro(self, coro):
        import asyncio
        return asyncio.run(coro)

    def _engine(self):
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.pool import NullPool
        url = DB_URL.split("?")[0]
        if url.startswith("postgresql://"):
            url = "postgresql+asyncpg://" + url.split("://", 1)[1]
        return create_async_engine(url, poolclass=NullPool)

    def test_agent_rejected_session_and_anonymous_unchanged(self):
        import hashlib
        import secrets
        from sqlalchemy import text
        from api.core.security import optional_actor

        async def body():
            eng = self._engine()
            tag = secrets.token_hex(5)
            try:
                async with eng.begin() as conn:
                    uid = (await conn.execute(text("""
                        INSERT INTO community.users
                          (username,email,password_hash,display_name)
                        VALUES (:u,:e,'x','Boundary') RETURNING id
                    """), {
                        "u": f"rab_{tag}", "e": f"rab_{tag}@example.test",
                    })).scalar_one()
                    plain = f"hgs_{secrets.token_urlsafe(36)}"
                    session_plain = secrets.token_urlsafe(32)
                    await conn.execute(text("""
                        INSERT INTO community.user_api_tokens
                          (user_id,name,token_hash,token_prefix)
                        VALUES (:uid,'boundary',:h,'pfxrab123')
                    """), {"uid": uid, "h": hashlib.sha256(plain.encode()).digest()})
                    await conn.execute(text("""
                        INSERT INTO community.sessions(user_id,token_hash,expires_at)
                        VALUES (:uid,:h,now()+interval '1 day')
                    """), {
                        "uid": uid,
                        "h": hashlib.sha256(session_plain.encode()).digest(),
                    })
                from fastapi import HTTPException
                from api.core import security

                async with eng.connect() as conn:
                    # ① AI Key → 401 + kind=rest_agent_forbidden
                    with self.assertRaises(HTTPException) as raised:
                        await security.optional_actor(
                            authorization=f"Bearer {plain}",
                            session_token=None, db=conn)
                    self.assertEqual(raised.exception.status_code, 401)
                    self.assertEqual(raised.exception.detail["kind"],
                                     "rest_agent_forbidden")

                    # ② 会话 cookie → 正常解析为 session actor
                    actor = await security.optional_actor(
                        authorization=None,
                        session_token=session_plain, db=conn)
                    self.assertIsNotNone(actor)
                    self.assertEqual(actor.auth_kind, "session")
                    self.assertEqual(actor.id, uid)

                    # ③ 匿名 → None(公开读取不受影响)
                    self.assertIsNone(await security.optional_actor(
                        authorization=None, session_token=None, db=conn))

                    # ④ 无效 AI Key(查无此 token) → None, 不误伤为 500
                    self.assertIsNone(await security.optional_actor(
                        authorization="Bearer hgs_does_not_exist_at_all",
                        session_token=None, db=conn))
                return uid
            finally:
                await eng.dispose()

        uid = self.run_coro(body())
        self.run_coro(self._cleanup(uid))

    def _cleanup(self, uid):
        from sqlalchemy import text

        async def go():
            eng = self._engine()
            try:
                async with eng.begin() as conn:
                    await conn.execute(text(
                        "DELETE FROM community.users WHERE id=:i"), {"i": uid})
            finally:
                await eng.dispose()
        return go()


@_GATE
class SearchErrorKindPayloadTests(unittest.TestCase):
    """搜索入口错误码: CAS 校验位错误 → 400 {message, kind=invalid_cas}。"""

    def run_coro(self, coro):
        import asyncio
        return asyncio.run(coro)

    def test_invalid_cas_checkdigit_returns_kind_payload(self):
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.pool import NullPool
        from fastapi import HTTPException
        from api.routes import search

        url = DB_URL.split("?")[0]
        if url.startswith("postgresql://"):
            url = "postgresql+asyncpg://" + url.split("://", 1)[1]
        eng = create_async_engine(url, poolclass=NullPool)

        class _Headers:
            def get(self, key, default=None):
                return default

        class _Request:
            headers = _Headers()

        async def body():
            try:
                async with eng.connect() as conn:
                    try:
                        await search(
                            request=_Request(),
                            actor=None, q="7732-18-6", mode="exact",
                            threshold=0.7, page=1, page_size=30, db=conn)
                    except HTTPException as exc:
                        return exc
                    return None
            finally:
                await eng.dispose()

        exc = self.run_coro(body())
        self.assertIsNotNone(exc, "校验位错误的 CAS 必须 400, 不是正常返回")
        self.assertEqual(exc.status_code, 400)
        self.assertEqual(exc.detail, {
            "message": "CAS 号校验位不正确", "kind": "invalid_cas"})


if __name__ == "__main__":
    unittest.main()
