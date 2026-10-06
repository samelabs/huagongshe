"""MCP OAuth boundary tests: mixed auth, challenges and auth_kind policy."""
from __future__ import annotations

import asyncio
import inspect
import os
import unittest

os.environ.setdefault(
    "HGS_DATABASE_URL",
    "postgresql+asyncpg://oauth:oauth@127.0.0.1:5432/unused",
)

from fastapi import HTTPException

from api.core.security import Actor, current_session
from api import mcp_server
from api.services import reactions as reaction_service
from api.services import skills as skill_service


class McpOAuthContractTests(unittest.TestCase):
    def test_challenge_contains_discovery_scope_and_error(self):
        result = mcp_server._oauth_challenge(
            "reaction:write",
            error="invalid_token",
            description="Authentication required.",
        )
        self.assertTrue(result.is_error)
        meta = result.meta or {}
        values = meta.get("mcp/www_authenticate") or []
        self.assertEqual(len(values), 1)
        self.assertIn(
            'resource_metadata="https://huagongshe.com/.well-known/oauth-protected-resource"',
            values[0],
        )
        self.assertIn('scope="reaction:write"', values[0])
        self.assertIn('error="invalid_token"', values[0])
        self.assertIn("error_description=", values[0])

    def test_oauth_actor_is_not_a_web_session(self):
        actor = Actor(
            1, "u", "User", "u@example.test", "member", None,
            "oauth", 1, ("read",),
        )
        with self.assertRaises(HTTPException) as raised:
            asyncio.run(current_session(actor))
        self.assertEqual(raised.exception.status_code, 403)

    def test_oauth_keeps_machine_credential_service_semantics(self):
        reactions = inspect.getsource(reaction_service)
        skills = inspect.getsource(skill_service)
        self.assertIn('auth_kind in ("agent", "oauth")', reactions)
        self.assertIn('"agent" if auth_kind in ("agent", "oauth") else "web"', reactions)
        self.assertIn('auth_kind in ("agent", "oauth")', skills)

    def test_optional_private_tools_use_read_scope_gate(self):
        source = inspect.getsource(mcp_server.build_mcp_server)
        for tool_name in ("get_reaction", "get_skill", "render_reaction_svg"):
            with self.subTest(tool=tool_name):
                start = source.index(f"async def {tool_name}(")
                tail = source[start:]
                next_tool = tail.find("@server.tool", 1)
                body = tail if next_tool < 0 else tail[:next_tool]
                self.assertIn("_optional_tool_actor(", body)
                self.assertIn('oauth_scope="read"', body)

    def test_rest_bearer_resolver_does_not_claim_oauth_tokens(self):
        from api.core import security
        source = inspect.getsource(security.resolve_actor)
        self.assertNotIn("hgo_at_", source)


if __name__ == "__main__":
    unittest.main()
