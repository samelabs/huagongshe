"""Pure OAuth 2.1 contract tests."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault(
    "HGS_DATABASE_URL",
    "postgresql+asyncpg://oauth:oauth@127.0.0.1:5432/unused",
)

from api.services import oauth as svc


class OAuthContractTests(unittest.TestCase):
    def test_discovery_metadata_is_truthful_dcr_pkce_contract(self):
        resource = svc.protected_resource_metadata()
        auth = svc.authorization_server_metadata()

        self.assertEqual(resource["resource"], "https://huagongshe.com/mcp")
        self.assertEqual(resource["authorization_servers"], ["https://huagongshe.com"])
        self.assertEqual(
            set(resource["scopes_supported"]),
            {"read", "reaction:write", "skill:write"},
        )
        self.assertEqual(auth["issuer"], "https://huagongshe.com")
        self.assertEqual(auth["authorization_endpoint"], "https://huagongshe.com/oauth/authorize")
        self.assertEqual(auth["token_endpoint"], "https://huagongshe.com/oauth/token")
        self.assertEqual(auth["registration_endpoint"], "https://huagongshe.com/oauth/register")
        self.assertEqual(auth["token_endpoint_auth_methods_supported"], ["none"])
        self.assertEqual(auth["code_challenge_methods_supported"], ["S256"])
        self.assertNotIn("client_id_metadata_document_supported", auth)
        self.assertNotIn("authorization_response_iss_parameter_supported", auth)

    def test_pkce_s256(self):
        verifier = "v" * 43
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        ).rstrip(b"=").decode()
        self.assertTrue(svc._verify_pkce(verifier, challenge))
        self.assertFalse(svc._verify_pkce("x" * 43, challenge))
        self.assertFalse(svc._verify_pkce("short", challenge))

    def test_redirect_uri_policy(self):
        self.assertTrue(svc._valid_redirect_uri("https://chatgpt.com/callback"))
        self.assertTrue(svc._valid_redirect_uri("http://127.0.0.1:7788/callback"))
        self.assertTrue(svc._valid_redirect_uri("http://localhost:7788/callback"))
        self.assertFalse(svc._valid_redirect_uri("http://example.com/callback"))
        self.assertFalse(svc._valid_redirect_uri("https://example.com/cb#fragment"))
        self.assertFalse(svc._valid_redirect_uri("javascript:alert(1)"))

    def test_scope_allowlist(self):
        self.assertEqual(svc._scope_tuple("read reaction:write"), ("read", "reaction:write"))
        with self.assertRaises(svc.OAuthProtocolError) as raised:
            svc._scope_tuple("read note:write")
        self.assertEqual(raised.exception.error, "invalid_scope")

    def test_dcr_rejects_malformed_metadata_before_db(self):
        class NeverDb:
            async def execute(self, *args, **kwargs):
                raise AssertionError("DB must not be touched for invalid DCR metadata")

        with self.assertRaises(svc.OAuthProtocolError) as raised:
            asyncio.run(svc.register_client(
                NeverDb(),
                redirect_uris=[123],
                client_name="bad",
                token_endpoint_auth_method="none",
                grant_types=["authorization_code"],
                response_types=["code"],
                application_type="web",
            ))
        self.assertEqual(raised.exception.error, "invalid_client_metadata")

    def test_dcr_default_grant_is_authorization_code_only(self):
        class CaptureDb:
            def __init__(self):
                self.params = None

            async def execute(self, statement, params=None):
                self.params = params

            async def commit(self):
                return None

        db = CaptureDb()
        registered = asyncio.run(svc.register_client(
            db,
            redirect_uris=["https://chatgpt.com/callback"],
            client_name="default grant",
            token_endpoint_auth_method="none",
            grant_types=None,
            response_types=None,
            application_type="web",
        ))
        self.assertEqual(registered["grant_types"], ["authorization_code"])
        self.assertEqual(registered["response_types"], ["code"])
        self.assertEqual(db.params["grant_types"], ["authorization_code"])

    def test_dcr_does_not_treat_explicit_empty_lists_as_omitted(self):
        class NeverDb:
            async def execute(self, *args, **kwargs):
                raise AssertionError("DB must not be touched for invalid DCR metadata")

        for grants, responses in (
            ([], ["code"]),
            (["authorization_code"], []),
        ):
            with self.subTest(grants=grants, responses=responses):
                with self.assertRaises(svc.OAuthProtocolError) as raised:
                    asyncio.run(svc.register_client(
                        NeverDb(),
                        redirect_uris=["https://chatgpt.com/callback"],
                        client_name="bad",
                        token_endpoint_auth_method="none",
                        grant_types=grants,
                        response_types=responses,
                        application_type="web",
                    ))
                self.assertEqual(raised.exception.error, "invalid_client_metadata")

    def test_authorization_errors_redirect_only_after_exact_redirect_validation(self):
        registered = "https://chatgpt.com/callback"
        client = {
            "client_id": "hgo_client_test",
            "client_name": "Test client",
            "redirect_uris": [registered],
        }

        with patch.object(svc, "_load_client", new=AsyncMock(return_value=client)):
            with self.assertRaises(svc.OAuthProtocolError) as raised:
                asyncio.run(svc.begin_authorization(
                    object(),
                    user_id=1,
                    client_id="hgo_client_test",
                    redirect_uri=registered,
                    response_type="code",
                    scope="read note:write",
                    state="state-1",
                    code_challenge="x" * 43,
                    code_challenge_method="S256",
                    resource=svc.mcp_resource_url(),
                ))
        self.assertEqual(raised.exception.error, "invalid_scope")
        self.assertEqual(raised.exception.redirect_uri, registered)
        self.assertEqual(raised.exception.state, "state-1")

        with patch.object(svc, "_load_client", new=AsyncMock(return_value=client)):
            with self.assertRaises(svc.OAuthProtocolError) as raised:
                asyncio.run(svc.begin_authorization(
                    object(),
                    user_id=1,
                    client_id="hgo_client_test",
                    redirect_uri="https://attacker.example/callback",
                    response_type="code",
                    scope="read",
                    state="state-2",
                    code_challenge="x" * 43,
                    code_challenge_method="S256",
                    resource=svc.mcp_resource_url(),
                ))
        self.assertEqual(raised.exception.error, "invalid_request")
        self.assertIsNone(raised.exception.redirect_uri)


if __name__ == "__main__":
    unittest.main()
