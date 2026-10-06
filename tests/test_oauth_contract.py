"""Pure OAuth 2.1 contract tests for v1.7.0."""

from __future__ import annotations

import os
import unittest
from pathlib import Path

os.environ.setdefault(
    "HGS_DATABASE_URL",
    "postgresql+asyncpg://oauth:oauth@127.0.0.1:5432/unused",
)

from api.services import oauth

REPO = Path(__file__).resolve().parents[1]


class OAuthContractTests(unittest.TestCase):
    def test_metadata_is_dcr_pkce_and_resource_bound(self):
        auth = oauth.authorization_server_metadata()
        resource = oauth.protected_resource_metadata()
        self.assertEqual(auth["issuer"], "https://huagongshe.com")
        self.assertEqual(auth["code_challenge_methods_supported"], ["S256"])
        self.assertEqual(auth["token_endpoint_auth_methods_supported"], ["none"])
        self.assertIn("registration_endpoint", auth)
        self.assertNotIn("client_id_metadata_document_supported", auth)
        self.assertNotIn("authorization_response_iss_parameter_supported", auth)
        self.assertEqual(resource["resource"], "https://huagongshe.com/mcp")
        self.assertEqual(resource["authorization_servers"], [auth["issuer"]])
        self.assertEqual(set(resource["scopes_supported"]), set(oauth.OAUTH_SCOPES))

    def test_pkce_s256(self):
        verifier = "A" * 43
        challenge = oauth.pkce_challenge(verifier)
        self.assertRegex(challenge, r"^[A-Za-z0-9_-]{43}$")
        with self.assertRaises(oauth.OAuthError):
            oauth.pkce_challenge("short")

    def test_oauth_is_mcp_only_at_rest_boundary(self):
        security = (REPO / "api/core/security.py").read_text(encoding="utf-8")
        self.assertNotIn("hgo_at_", security)
        mcp = (REPO / "api/mcp_server.py").read_text(encoding="utf-8")
        self.assertIn('token.startswith("hgo_at_")', mcp)
        self.assertIn("resolve_access_token", mcp)

    def test_public_discovery_routes_are_real_next_routes(self):
        self.assertTrue(
            (REPO / "web/app/.well-known/oauth-protected-resource/route.ts").exists()
        )
        self.assertTrue(
            (REPO / "web/app/.well-known/oauth-authorization-server/route.ts").exists()
        )
        page = (REPO / "web/app/(site)/oauth/authorize/page.tsx").read_text(encoding="utf-8")
        self.assertIn('action="/api/oauth/authorize"', page)

    def test_credentials_are_hash_only_in_oauth_schema(self):
        migration = (REPO / "migrations/20261006_02_oauth.sql").read_text(encoding="utf-8")
        self.assertIn("token_hash bytea", migration)
        self.assertIn("code_hash bytea", migration)
        self.assertIn("issuer text NOT NULL", migration)
        self.assertNotIn("token_plain", migration)
        self.assertNotIn("code_plain", migration)


if __name__ == "__main__":
    unittest.main()
