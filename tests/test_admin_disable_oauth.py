"""F-OAUTH-01 回归 —— 管理员停用账号撤销 OAuth 凭证（hermetic，需 test DB）。

事故：admin set_user_status(disabled) 只删 sessions/API Key，不撤 OAuth ——
停用期间可用 refresh token 继续轮换、用未用 code 兑换新凭证，重新启用后
旧授权直接复活。

锁三条：
1. 停用同事务清空四类 OAuth 凭证（authorization_requests / codes /
   access / refresh），客户端注册保留（与 change_password 同口径）；
2. 停用 → 旧 refresh 兑换失败；重新启用 → 旧凭证仍失效（行已物理删除）；
3. 防线复核：即使有「停用后残留/竞态插入」的凭证行，refresh 与 code
   兑换前的 active 复核（JOIN community.users status='active'）也必须拒绝。
"""
from __future__ import annotations

import base64
import hashlib
import re
import unittest
import uuid
from urllib.parse import parse_qs, urlparse

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
    ASYNC_URL = re.sub(r"^postgres(?:ql)?://", "postgresql+asyncpg://", _raw.split("?")[0])

from api.services import oauth as svc


@unittest.skipUnless(ASYNC_URL, "测试库闸: TEST_DATABASE_URL 未过 tests/db_gate.py")
class AdminDisableOauthTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine(ASYNC_URL)
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        self.tag = uuid.uuid4().hex[:10]
        async with self.engine.begin() as conn:
            self.user_id = int((await conn.execute(text("""
                INSERT INTO community.users(username,email,password_hash,display_name)
                VALUES (:u,:e,'x',:d) RETURNING id
            """), {
                "u": f"oadm_{self.tag}",
                "e": f"oadm_{self.tag}@example.test",
                "d": "Admin Disable Test",
            })).scalar_one())

    async def asyncTearDown(self):
        async with self.engine.begin() as conn:
            for table in ("oauth_authorization_requests", "oauth_authorization_codes",
                          "oauth_access_tokens", "oauth_refresh_tokens"):
                await conn.execute(text(
                    f"DELETE FROM community.{table} WHERE user_id=:id"
                ), {"id": self.user_id})
            await conn.execute(
                text("DELETE FROM community.oauth_clients WHERE client_name LIKE 'Admin disable %'")
            )
            await conn.execute(
                text("DELETE FROM community.users WHERE id=:id"), {"id": self.user_id}
            )
        await self.engine.dispose()

    async def _issue_full_grant(self):
        """DCR → PKCE code → 兑换（拿 refresh/access），另留一条 pending 授权请求。"""
        redirect_uri = "https://chatgpt.com/connector/oauth/admin-disable"
        verifier = "d" * 43
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        ).rstrip(b"=").decode()
        async with self.Session() as db:
            client = await svc.register_client(
                db,
                redirect_uris=[redirect_uri],
                client_name="Admin disable test",
                token_endpoint_auth_method="none",
                grant_types=["authorization_code", "refresh_token"],
                response_types=["code"],
                application_type="web",
            )
            pending = await svc.begin_authorization(
                db, user_id=self.user_id, client_id=client["client_id"],
                redirect_uri=redirect_uri, response_type="code", scope="read",
                state=None, code_challenge=challenge, code_challenge_method="S256",
                resource=svc.mcp_resource_url(),
            )
            redirect = await svc.complete_authorization(
                db, user_id=self.user_id,
                request_id=pending["request_id"], approve=True,
            )
            code = parse_qs(urlparse(redirect).query)["code"][0]
            tokens = await svc.exchange_authorization_code(
                db, client_id=client["client_id"], code=code,
                redirect_uri=redirect_uri, code_verifier=verifier,
                resource=svc.mcp_resource_url(),
            )
            # 再留一条 pending 授权请求（未到 code 阶段的第一类凭证）
            await svc.begin_authorization(
                db, user_id=self.user_id, client_id=client["client_id"],
                redirect_uri=redirect_uri, response_type="code", scope="read",
                state=None, code_challenge=challenge, code_challenge_method="S256",
                resource=svc.mcp_resource_url(),
            )
            return client, redirect_uri, verifier, challenge, tokens

    async def _count(self, db, table: str) -> int:
        return int((await db.execute(text(
            f"SELECT count(*) FROM community.{table} WHERE user_id=:id"
        ), {"id": self.user_id})).scalar_one())

    async def _set_status(self, db, status: str):
        from api import admin
        from api.core.security import Actor
        from api.schemas.admin import UserStatusBody

        admin_actor = Actor(
            999999, "admin", "Admin", "admin@example.test", "admin", None, "session",
        )
        return await admin.set_user_status(
            self.user_id, UserStatusBody(status=status), admin_actor, db)

    async def test_disable_revokes_oauth_and_survives_reenable(self):
        from api.services.oauth import OAuthProtocolError

        client, redirect_uri, verifier, challenge, tokens = await self._issue_full_grant()
        refresh_token = tokens["refresh_token"]

        async with self.Session() as db:
            # ① 停用：四表清空 + 客户端保留
            await self._set_status(db, "disabled")
            for table in ("oauth_authorization_requests", "oauth_authorization_codes",
                          "oauth_access_tokens", "oauth_refresh_tokens"):
                self.assertEqual(await self._count(db, table), 0, table)
            client_count = int((await db.execute(text(
                "SELECT count(*) FROM community.oauth_clients WHERE client_id=:c"
            ), {"c": client["client_id"]})).scalar_one())
            self.assertEqual(client_count, 1)

            # ② 停用期间旧 refresh 失效
            with self.assertRaises(OAuthProtocolError):
                await svc.refresh_access_token(
                    db, client_id=client["client_id"], refresh_token=refresh_token,
                    scope=None, resource=svc.mcp_resource_url())

            # ③ 重新启用：旧凭证仍失效（物理删除，不可复活）
            await self._set_status(db, "active")
            with self.assertRaises(OAuthProtocolError):
                await svc.refresh_access_token(
                    db, client_id=client["client_id"], refresh_token=refresh_token,
                    scope=None, resource=svc.mcp_resource_url())

    async def test_leftover_credential_blocked_by_active_recheck(self):
        """防线：停用状态下即便存在（竞态/残留）凭证行，兑换前 active 复核拒绝。"""
        from api.services.oauth import OAuthProtocolError, _digest

        client, redirect_uri, verifier, challenge, tokens = await self._issue_full_grant()
        async with self.Session() as db:
            await self._set_status(db, "disabled")
            # 伪造停用后残留的 refresh 行（正常路径已被同事务删除 —— 这里验证第二道闸）
            await db.execute(text("""
                INSERT INTO community.oauth_refresh_tokens
                  (token_hash,user_id,client_id,scopes,resource,expires_at)
                VALUES (:h,:u,:c,CAST(:s AS text[]),:r,now()+interval '1 hour')
            """), {
                "h": _digest("leftover-refresh"), "u": self.user_id,
                "c": client["client_id"], "s": ["read"],
                "r": svc.mcp_resource_url(),
            })
            await db.commit()
            with self.assertRaises(OAuthProtocolError):
                await svc.refresh_access_token(
                    db, client_id=client["client_id"],
                    refresh_token="leftover-refresh",
                    scope=None, resource=svc.mcp_resource_url())
            await db.rollback()

            # 同法验证 code 兑换的 active 复核
            await db.execute(text("""
                INSERT INTO community.oauth_authorization_codes
                  (code_hash,user_id,client_id,redirect_uri,scopes,resource,
                   code_challenge,expires_at)
                VALUES (:h,:u,:c,:rd,CAST(:s AS text[]),:r,:cc,
                        now()+interval '10 minutes')
            """), {
                "h": _digest("leftover-code"), "u": self.user_id,
                "c": client["client_id"], "rd": redirect_uri, "s": ["read"],
                "r": svc.mcp_resource_url(), "cc": challenge,
            })
            await db.commit()
            with self.assertRaises(OAuthProtocolError):
                await svc.exchange_authorization_code(
                    db, client_id=client["client_id"], code="leftover-code",
                    redirect_uri=redirect_uri, code_verifier=verifier,
                    resource=svc.mcp_resource_url())


if __name__ == "__main__":
    unittest.main()
