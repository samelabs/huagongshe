"""OAuth persistence integration: DCR -> PKCE code -> tokens -> refresh rotation."""
from __future__ import annotations

import base64
import hashlib
import re
import unittest
import uuid
from unittest.mock import patch
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

    async def test_authorization_code_only_client_gets_no_refresh_token(self):
        redirect_uri = "https://chatgpt.com/connector/oauth/code-only"
        verifier = "c" * 43
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        ).rstrip(b"=").decode()

        async with self.Session() as db:
            client = await svc.register_client(
                db,
                redirect_uris=[redirect_uri],
                client_name="Code only",
                token_endpoint_auth_method="none",
                grant_types=None,
                response_types=None,
                application_type="web",
            )
            self.assertEqual(client["grant_types"], ["authorization_code"])
            pending = await svc.begin_authorization(
                db,
                user_id=self.user_id,
                client_id=client["client_id"],
                redirect_uri=redirect_uri,
                response_type="code",
                scope="read",
                state=None,
                code_challenge=challenge,
                code_challenge_method="S256",
                resource=svc.mcp_resource_url(),
            )
            redirect = await svc.complete_authorization(
                db, user_id=self.user_id,
                request_id=pending["request_id"], approve=True,
            )
            code = parse_qs(urlparse(redirect).query)["code"][0]
            tokens = await svc.exchange_authorization_code(
                db,
                client_id=client["client_id"],
                code=code,
                redirect_uri=redirect_uri,
                code_verifier=verifier,
                resource=svc.mcp_resource_url(),
            )
            self.assertNotIn("refresh_token", tokens)
            with self.assertRaises(svc.OAuthProtocolError) as denied:
                await svc.refresh_access_token(
                    db,
                    client_id=client["client_id"],
                    refresh_token="hgo_rt_not-issued",
                    scope="read",
                    resource=svc.mcp_resource_url(),
                )
            self.assertEqual(denied.exception.error, "unauthorized_client")

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
            self.assertEqual(bad_resource.exception.redirect_uri, redirect_uri)

            with self.assertRaises(svc.OAuthProtocolError) as bad_redirect:
                await svc.begin_authorization(
                    db,
                    user_id=self.user_id,
                    client_id=client["client_id"],
                    redirect_uri=redirect_uri + "/not-registered",
                    response_type="code",
                    scope="read",
                    state="state-bad-redirect",
                    code_challenge=challenge,
                    code_challenge_method="S256",
                    resource=svc.mcp_resource_url(),
                )
            self.assertIsNone(bad_redirect.exception.redirect_uri)

            pending = await svc.begin_authorization(
                db,
                user_id=self.user_id,
                client_id=client["client_id"],
                redirect_uri=redirect_uri,
                response_type="code",
                scope="read",
                state=None,
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
            code = parse_qs(urlparse(redirect).query)["code"][0]
            with self.assertRaises(svc.OAuthProtocolError) as bad_pkce:
                await svc.exchange_authorization_code(
                    db,
                    client_id=client["client_id"],
                    code=code,
                    redirect_uri=redirect_uri,
                    code_verifier="x" * 43,
                    resource=svc.mcp_resource_url(),
                )
            self.assertEqual(bad_pkce.exception.error, "invalid_grant")

    async def test_access_token_invalid_expired_revoked_resource_and_client_disable(self):
        redirect_uri = "https://chatgpt.com/connector/oauth/access-state"
        verifier = "a" * 43
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        ).rstrip(b"=").decode()

        async with self.Session() as db:
            client = await svc.register_client(
                db,
                redirect_uris=[redirect_uri],
                client_name="Access state test",
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
                scope="read",
                state=None,
                code_challenge=challenge,
                code_challenge_method="S256",
                resource=svc.mcp_resource_url(),
            )
            redirect = await svc.complete_authorization(
                db, user_id=self.user_id,
                request_id=pending["request_id"], approve=True,
            )
            code = parse_qs(urlparse(redirect).query)["code"][0]
            tokens = await svc.exchange_authorization_code(
                db,
                client_id=client["client_id"],
                code=code,
                redirect_uri=redirect_uri,
                code_verifier=verifier,
                resource=svc.mcp_resource_url(),
            )
            access = tokens["access_token"]

            self.assertIsNone(await svc.resolve_access_token(
                db, "hgo_at_not-a-real-token",
                expected_resource=svc.mcp_resource_url(),
            ))
            self.assertIsNone(await svc.resolve_access_token(
                db, access, expected_resource="https://example.test/mcp",
            ))

            await db.execute(text("""
                UPDATE community.oauth_access_tokens
                SET revoked_at=now()
                WHERE token_hash=:digest
            """), {"digest": svc._digest(access)})
            await db.commit()
            self.assertIsNone(await svc.resolve_access_token(
                db, access, expected_resource=svc.mcp_resource_url(),
            ))

            await db.execute(text("""
                UPDATE community.oauth_access_tokens
                SET revoked_at=NULL, expires_at=now()-interval '1 second'
                WHERE token_hash=:digest
            """), {"digest": svc._digest(access)})
            await db.commit()
            self.assertIsNone(await svc.resolve_access_token(
                db, access, expected_resource=svc.mcp_resource_url(),
            ))

            await db.execute(text("""
                UPDATE community.oauth_access_tokens
                SET expires_at=now()+interval '1 hour'
                WHERE token_hash=:digest
            """), {"digest": svc._digest(access)})
            await db.execute(text("""
                UPDATE community.oauth_clients
                SET disabled_at=now()
                WHERE client_id=:client_id
            """), {"client_id": client["client_id"]})
            await db.commit()
            self.assertIsNone(await svc.resolve_access_token(
                db, access, expected_resource=svc.mcp_resource_url(),
            ))

    async def test_password_change_revokes_all_oauth_grants_but_keeps_client(self):
        from fastapi import Response

        from api import users
        from api.core.security import Actor
        from api.schemas.users import PasswordBody

        redirect_uri = "https://chatgpt.com/connector/oauth/password-rotation"
        verifier = "z" * 43
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        ).rstrip(b"=").decode()

        async with self.Session() as db:
            client = await svc.register_client(
                db,
                redirect_uris=[redirect_uri],
                client_name="Password rotation test",
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
                scope="read",
                state=None,
                code_challenge=challenge,
                code_challenge_method="S256",
                resource=svc.mcp_resource_url(),
            )
            redirect = await svc.complete_authorization(
                db, user_id=self.user_id,
                request_id=pending["request_id"], approve=True,
            )
            code = parse_qs(urlparse(redirect).query)["code"][0]
            await svc.exchange_authorization_code(
                db,
                client_id=client["client_id"],
                code=code,
                redirect_uri=redirect_uri,
                code_verifier=verifier,
                resource=svc.mcp_resource_url(),
            )
            # Keep one still-pending authorization request as well, so password
            # rotation proves all four user-owned OAuth grant tables are cleared.
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
                resource=svc.mcp_resource_url(),
            )

            async def no_enforce(*args, **kwargs):
                return None

            actor = Actor(
                self.user_id,
                f"oauth_{self.tag}",
                "OAuth Test",
                f"oauth_{self.tag}@example.test",
                "member",
                None,
                "session",
            )
            body = PasswordBody(
                current_password="old-password",
                new_password="NewPassword123",
                confirm_password="NewPassword123",
            )
            with patch.object(users, "enforce_http", new=no_enforce), \
                 patch.object(users, "password_matches", return_value=True), \
                 patch.object(users, "password_hash", return_value="rotated-hash"):
                await users.change_password(body, Response(), actor, db)

            for table in (
                "oauth_authorization_requests",
                "oauth_authorization_codes",
                "oauth_access_tokens",
                "oauth_refresh_tokens",
            ):
                count = int((await db.execute(text(
                    f"SELECT count(*) FROM community.{table} WHERE user_id=:id"
                ), {"id": self.user_id})).scalar_one())
                self.assertEqual(count, 0, table)

            client_count = int((await db.execute(text("""
                SELECT count(*) FROM community.oauth_clients
                WHERE client_id=:client_id
            """), {"client_id": client["client_id"]})).scalar_one())
            self.assertEqual(client_count, 1)


if __name__ == "__main__":
    unittest.main()
