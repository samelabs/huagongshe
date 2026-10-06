"""Pure OAuth 2.1 contract tests."""
from __future__ import annotations

import base64
import hashlib
import os
import unittest

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


if __name__ == "__main__":
    unittest.main()
