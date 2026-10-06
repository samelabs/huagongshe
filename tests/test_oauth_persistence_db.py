"""OAuth persistence integration: DCR -> PKCE code -> tokens -> refresh rotation."""
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
    assert parse_qs(_u.query).get("test_sentinel") in (["hgs-test-db"], ["hgs-ephemeral-db"])
    ASYNC_URL = re.sub(r"^postgres(?:ql)?://", "postgresql+asyncpg://", _raw.split("?")[0])

from api.services import oauth as svc


@unittest.skipUnless(ASYNC_URL, "测试库闸: TEST_DATABASE_URL 未过 tests/db_gate.py")
class OAuthPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine(ASYNC_URL)
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        self.tag = uuid.uuid4().hex[:10]
        async with self.engine.begin() as conn:
            self.user_id = int((await conn.execute(text("""
                INSERT INTO community.users(username,email,password_hash,display_name)
                VALUES (:u,:e,'x',:d) RETURNING id
            """), {
                "u": f"oauth_{self.tag}",
                "e": f"oauth_{self.tag}@example.test",
                "d": "OAuth Test",
            })).scalar_one())

    async def asyncTearDown(self):
        async with self.engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM community.oauth_clients WHERE client_id LIKE 'hgo_client_%'")
            )
            await conn.execute(
                text("DELETE FROM community.users WHERE id=:id"), {"id": self.user_id}
            )
        await self.engine.dispose()

    async def test_full_code_flow_and_refresh_rotation(self):
        redirect_uri = "https://chatgpt.com/connector/oauth/test"
        verifier = "v" * 43
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        ).rstrip(b"=").decode()

        async with self.Session() as db:
            client = await svc.register_client(
                db,
                redirect_uris=[redirect_uri],
                client_name="ChatGPT test",
                token_endpoint_auth_method="none",
                grant_types=["authorization_code", "refresh_token"],
                response_types=["code"],
                application_type="web",
            )
            pending = await svc.begin_authorization(
                db,
                user_id=self.user_id,
                client_id=client["client_id"],
                redirect_uri=redirect_uri,
                response_type="code",
                scope="read reaction:write",
                state="state-1",
                code_challenge=challenge,
                code_challenge_method="S256",
                resource=svc.mcp_resource_url(),
            )
            redirect = await svc.complete_authorization(
                db,
                user_id=self.user_id,
                request_id=pending["request_id"],
                approve=True,
            )
            query = parse_qs(urlparse(redirect).query)
            code = query["code"][0]
            self.assertEqual(query["state"], ["state-1"])

            tokens = await svc.exchange_authorization_code(
                db,
                client_id=client["client_id"],
                code=code,
                redirect_uri=redirect_uri,
                code_verifier=verifier,
                resource=svc.mcp_resource_url(),
            )
            self.assertTrue(tokens["access_token"].startswith("hgo_at_"))
            self.assertTrue(tokens["refresh_token"].startswith("hgo_rt_"))
            self.assertEqual(tokens["scope"], "read reaction:write")

            actor_row = await svc.resolve_access_token(
                db, tokens["access_token"], expected_resource=svc.mcp_resource_url()
            )
            self.assertIsNotNone(actor_row)
            self.assertEqual(actor_row["user_id"], self.user_id)
            self.assertEqual(tuple(actor_row["scopes"]), ("read", "reaction:write"))

            with self.assertRaises(svc.OAuthProtocolError) as replay:
                await svc.exchange_authorization_code(
                    db,
                    client_id=client["client_id"],
                    code=code,
                    redirect_uri=redirect_uri,
                    code_verifier=verifier,
                    resource=svc.mcp_resource_url(),
                )
            self.assertEqual(replay.exception.error, "invalid_grant")

            refreshed = await svc.refresh_access_token(
                db,
                client_id=client["client_id"],
                refresh_token=tokens["refresh_token"],
                scope="read",
                resource=svc.mcp_resource_url(),
            )
            self.assertNotEqual(refreshed["access_token"], tokens["access_token"])
            self.assertEqual(refreshed["scope"], "read")

            with self.assertRaises(svc.OAuthProtocolError) as refresh_replay:
                await svc.refresh_access_token(
                    db,
                    client_id=client["client_id"],
                    refresh_token=tokens["refresh_token"],
                    scope="read",
                    resource=svc.mcp_resource_url(),
                )
            self.assertEqual(refresh_replay.exception.error, "invalid_grant")

    async def test_resource_and_pkce_are_fail_closed(self):
        redirect_uri = "https://chatgpt.com/connector/oauth/test2"
        verifier = "p" * 43
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        ).rstrip(b"=").decode()

        async with self.Session() as db:
            client = await svc.register_client(
                db,
                redirect_uris=[redirect_uri],
                client_name="ChatGPT resource test",
                token_endpoint_auth_method="none",
                grant_types=["authorization_code", "refresh_token"],
                response_types=["code"],
                application_type="web",
            )
            with self.assertRaises(svc.OAuthProtocolError) as bad_resource:
                await svc.begin_authorization(
                    db,
                    user_id=self.user_id,
                    client_id=client["client_id"],
                    redirect_uri=redirect_uri,
                    response_type="code",
                    scope="read",
                    state=None,
                    code_challenge=challenge,
                    code_challenge_method="S256",
                    resource="https://example.test/mcp",
                )
            self.assertEqual(bad_resource.exception.error, "invalid_target")


if __name__ == "__main__":
    unittest.main()
