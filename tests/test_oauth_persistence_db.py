"""OAuth DCR, PKCE, token binding, and refresh rotation integration tests."""

from __future__ import annotations

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
    assert parse_qs(_u.query).get("test_sentinel") in (
        ["hgs-test-db"], ["hgs-ephemeral-db"]
    )
    ASYNC_URL = re.sub(
        r"^postgres(?:ql)?://",
        "postgresql+asyncpg://",
        _raw.split("?")[0],
    )

from api.services import oauth


@unittest.skipUnless(ASYNC_URL, "测试库闸: TEST_DATABASE_URL 未过 tests/db_gate.py")
class OAuthPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine(ASYNC_URL)
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        self.tag = uuid.uuid4().hex[:12]
        async with self.engine.begin() as conn:
            self.user_id = int((await conn.execute(text("""
                INSERT INTO community.users(username,email,password_hash,display_name)
                VALUES (:u,:e,'x',:d) RETURNING id
            """), {
                "u": f"oauth_{self.tag}",
                "e": f"oauth_{self.tag}@example.test",
                "d": "OAuth Test User",
            })).scalar_one())

    async def asyncTearDown(self):
        async with self.engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM community.users WHERE id=:id"),
                {"id": self.user_id},
            )
            await conn.execute(
                text("DELETE FROM community.oauth_clients WHERE client_name=:name"),
                {"name": f"OAuth Client {self.tag}"},
            )
        await self.engine.dispose()

    async def _client(self, db):
        return await oauth.register_client(
            db,
            redirect_uris=[f"https://client.example/{self.tag}/callback"],
            client_name=f"OAuth Client {self.tag}",
            token_endpoint_auth_method="none",
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            scope="read reaction:write skill:write",
        )

    async def test_authorization_code_pkce_access_and_refresh_rotation(self):
        verifier = "V" * 43
        challenge = oauth.pkce_challenge(verifier)
        async with self.Session() as db:
            client = await self._client(db)
            request = await oauth.validate_authorization_request(
                db,
                response_type="code",
                client_id=client["client_id"],
                redirect_uri=client["redirect_uris"][0],
                scope="read reaction:write",
                code_challenge=challenge,
                code_challenge_method="S256",
                resource=oauth.mcp_resource_url(),
            )
            code = await oauth.create_authorization_code(
                db,
                user_id=self.user_id,
                client_id=client["client_id"],
                redirect_uri=client["redirect_uris"][0],
                scopes=tuple(request["scopes"]),
                code_challenge=challenge,
                resource=oauth.mcp_resource_url(),
            )
            tokens = await oauth.exchange_authorization_code(
                db,
                code=code,
                client_id=client["client_id"],
                redirect_uri=client["redirect_uris"][0],
                code_verifier=verifier,
                resource=oauth.mcp_resource_url(),
            )
            self.assertTrue(tokens["access_token"].startswith("hgo_at_"))
            self.assertTrue(tokens["refresh_token"].startswith("hgo_rt_"))

            actor = await oauth.resolve_access_token(
                db,
                tokens["access_token"],
                expected_resource=oauth.mcp_resource_url(),
            )
            self.assertIsNotNone(actor)
            self.assertEqual(actor["user_id"], self.user_id)
            self.assertEqual(actor["issuer"], oauth.issuer_url())
            self.assertEqual(tuple(actor["scopes"]), ("read", "reaction:write"))
            self.assertIsNone(await oauth.resolve_access_token(
                db,
                tokens["access_token"],
                expected_resource="https://huagongshe.com/not-mcp",
            ))

            with self.assertRaises(oauth.OAuthError) as code_replay:
                await oauth.exchange_authorization_code(
                    db,
                    code=code,
                    client_id=client["client_id"],
                    redirect_uri=client["redirect_uris"][0],
                    code_verifier=verifier,
                    resource=oauth.mcp_resource_url(),
                )
            self.assertEqual(code_replay.exception.error, "invalid_grant")

            rotated = await oauth.exchange_refresh_token(
                db,
                refresh_token=tokens["refresh_token"],
                client_id=client["client_id"],
                resource=oauth.mcp_resource_url(),
                scope="read",
            )
            self.assertEqual(rotated["scope"], "read")
            with self.assertRaises(oauth.OAuthError) as replay:
                await oauth.exchange_refresh_token(
                    db,
                    refresh_token=tokens["refresh_token"],
                    client_id=client["client_id"],
                    resource=oauth.mcp_resource_url(),
                    scope=None,
                )
            self.assertEqual(replay.exception.error, "invalid_grant")

    async def test_wrong_pkce_or_resource_is_rejected(self):
        verifier = "P" * 43
        async with self.Session() as db:
            client = await self._client(db)
            code = await oauth.create_authorization_code(
                db,
                user_id=self.user_id,
                client_id=client["client_id"],
                redirect_uri=client["redirect_uris"][0],
                scopes=("read",),
                code_challenge=oauth.pkce_challenge(verifier),
                resource=oauth.mcp_resource_url(),
            )
            with self.assertRaises(oauth.OAuthError):
                await oauth.exchange_authorization_code(
                    db,
                    code=code,
                    client_id=client["client_id"],
                    redirect_uri=client["redirect_uris"][0],
                    code_verifier="Q" * 43,
                    resource=oauth.mcp_resource_url(),
                )
            with self.assertRaises(oauth.OAuthError):
                await oauth.validate_authorization_request(
                    db,
                    response_type="code",
                    client_id=client["client_id"],
                    redirect_uri=client["redirect_uris"][0],
                    scope="read",
                    code_challenge=oauth.pkce_challenge(verifier),
                    code_challenge_method="S256",
                    resource="https://huagongshe.com/not-mcp",
                )
            with self.assertRaises(oauth.OAuthError):
                await oauth.validate_authorization_request(
                    db,
                    response_type="code",
                    client_id=client["client_id"],
                    redirect_uri="https://attacker.example/callback",
                    scope="read",
                    code_challenge=oauth.pkce_challenge(verifier),
                    code_challenge_method="S256",
                    resource=oauth.mcp_resource_url(),
                )

    async def test_expired_access_token_fails_closed(self):
        verifier = "E" * 43
        async with self.Session() as db:
            client = await self._client(db)
            code = await oauth.create_authorization_code(
                db,
                user_id=self.user_id,
                client_id=client["client_id"],
                redirect_uri=client["redirect_uris"][0],
                scopes=("read",),
                code_challenge=oauth.pkce_challenge(verifier),
                resource=oauth.mcp_resource_url(),
            )
            tokens = await oauth.exchange_authorization_code(
                db,
                code=code,
                client_id=client["client_id"],
                redirect_uri=client["redirect_uris"][0],
                code_verifier=verifier,
                resource=oauth.mcp_resource_url(),
            )
            await db.execute(text("""
                UPDATE community.oauth_access_tokens
                SET expires_at=now()-interval '1 second'
                WHERE token_hash=:digest
            """), {"digest": oauth.token_hash(tokens["access_token"])})
            await db.commit()
            self.assertIsNone(await oauth.resolve_access_token(
                db,
                tokens["access_token"],
                expected_resource=oauth.mcp_resource_url(),
            ))


if __name__ == "__main__":
    unittest.main()
