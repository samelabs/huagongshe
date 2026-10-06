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

    def test_existing_ai_key_path_is_preserved(self):
        src = inspect.getsource(mcp_server._actor_from_headers)
        self.assertIn('token.startswith("hgo_at_")', src)
        self.assertIn("resolve_actor(", src)


if __name__ == "__main__":
    unittest.main()
