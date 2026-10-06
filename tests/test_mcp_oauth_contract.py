"""MCP OAuth boundary tests that do not require PostgreSQL."""

from __future__ import annotations

import asyncio
import inspect
import os
import unittest

os.environ.setdefault(
    "HGS_DATABASE_URL",
    "postgresql+asyncpg://oauth:oauth@127.0.0.1:5432/unused",
)

from api import mcp_server
from api.services import reactions, skills


class McpOAuthContractTests(unittest.TestCase):
    def test_challenge_has_required_openai_metadata(self):
        result = mcp_server._oauth_challenge(
            "reaction:write",
            error="insufficient_scope",
            description="Need reaction write access.",
        )
        self.assertTrue(result.is_error)
        meta = result.meta or {}
        values = meta.get("mcp/www_authenticate") or []
        self.assertEqual(len(values), 1)
        self.assertIn("oauth-protected-resource", values[0])
        self.assertIn('error="insufficient_scope"', values[0])
        self.assertIn('error_description="Need reaction write access."', values[0])

    def test_oauth_is_classified_as_agent_for_mutation_semantics(self):
        reaction_src = inspect.getsource(reactions.create_reaction)
        skill_src = inspect.getsource(skills.create_skill)
        self.assertIn('auth_kind in ("agent", "oauth")', reaction_src)
        self.assertIn('auth_kind in ("agent", "oauth")', skill_src)
        self.assertIn(
            '"created_via": "agent" if auth_kind in ("agent", "oauth") else "web"',
            reaction_src,
        )

    def test_optional_private_tools_enforce_oauth_read_scope(self):
        source = inspect.getsource(mcp_server.build_mcp_server)
        for tool_name in ("get_reaction", "get_skill", "render_reaction_svg"):
            with self.subTest(tool=tool_name):
                start = source.index(f"async def {tool_name}(")
                tail = source[start:]
                next_tool = tail.find("@server.tool", 1)
                body = tail if next_tool < 0 else tail[:next_tool]
                self.assertIn("_optional_tool_actor(", body)
                self.assertIn('oauth_scope="read"', body)

    def test_invalid_ai_key_does_not_masquerade_as_oauth_relink(self):
        source = inspect.getsource(mcp_server._require_tool_actor)
        self.assertIn('startswith("hgs_")', source)
        self.assertIn("Connect an HGS AI Key", source)

    def test_existing_ai_key_path_is_preserved(self):
        src = inspect.getsource(mcp_server._actor_from_headers)
        self.assertIn('token.startswith("hgo_at_")', src)
        self.assertIn("resolve_actor(", src)


if __name__ == "__main__":
    unittest.main()
