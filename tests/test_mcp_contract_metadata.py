"""v1.7.0 MCP agent-facing contract metadata.

Locks only externally exposed MCP metadata. Business behavior remains covered by
the existing service/governance tests.
"""

from __future__ import annotations

import asyncio
import os
import re
import unittest

os.environ.setdefault(
    "HGS_DATABASE_URL",
    "postgresql+asyncpg://metadata:metadata@127.0.0.1:5432/unused",
)

from api.mcp_server import build_mcp_server

CJK_RE = re.compile(r"[\u3400-\u9fff]")

EXPECTED = {
    "search_chemistry_data": (False, False, False, True),
    "get_chemical": (False, False, False, True),
    "get_reaction": (True, False, True, False),
    "render_molecule_svg": (True, False, True, False),
    "render_reaction_svg": (True, False, True, False),
    "list_skills": (True, False, True, False),
    "get_skill": (True, False, True, False),
    "calculate_stoichiometry": (True, False, True, False),
    "list_my_reactions": (True, False, True, False),
    "validate_reaction": (True, False, True, False),
    "validate_skill": (True, False, True, False),
    "create_skill": (False, False, True, False),
    "create_reaction": (False, False, True, True),
}


class McpMetadataContractTests(unittest.TestCase):
    def setUp(self):
        self.server = build_mcp_server()
        self.tools = {tool.name: tool for tool in asyncio.run(self.server.list_tools())}

    def test_exact_tool_surface_and_annotation_matrix(self):
        self.assertEqual(set(self.tools), set(EXPECTED))
        self.assertEqual(len(self.tools), 13)
        for name, expected in EXPECTED.items():
            with self.subTest(tool=name):
                annotations = self.tools[name].annotations
                self.assertIsNotNone(annotations)
                actual = (
                    annotations.read_only_hint,
                    annotations.destructive_hint,
                    annotations.idempotent_hint,
                    annotations.open_world_hint,
                )
                self.assertEqual(actual, expected)

    def test_agent_facing_server_and_tool_metadata_is_english(self):
        values = [
            self.server.title or "",
            self.server.instructions or "",
        ]
        for tool in self.tools.values():
            values.extend([tool.title or "", tool.description or ""])
        bad = [value for value in values if CJK_RE.search(value)]
        self.assertEqual(bad, [], f"agent-facing MCP metadata still contains CJK: {bad}")

    def test_error_translation_preserves_dynamic_context(self):
        import api.mcp_server as mcp

        class ReactionError(Exception):
            kind = "invalid_structure"
            detail = "无法解析参与物结构：$$"

        self.assertEqual(
            mcp._reaction_error_message(ReactionError()),
            "Could not parse reaction participant structure: $$",
        )
        self.assertEqual(
            mcp._stoichiometry_error_message(
                ValueError("基准 index 9 超出组分范围")
            ),
            "Basis index 9 is outside the component range.",
        )

    def test_oauth_security_metadata_is_not_advertised_before_runtime(self):
        # W4 owns OAuth runtime + per-tool security metadata. W3 must not
        # promise oauth2 before the server can actually complete that flow.
        for name, tool in self.tools.items():
            with self.subTest(tool=name):
                meta = getattr(tool, "meta", None) or {}
                self.assertNotIn("securitySchemes", meta)

    def test_annotations_explain_known_non_read_side_effects(self):
        # These two tools are intentionally not marked read-only even though
        # their names look read-like:
        # - exact search can create/queue source work on misses
        # - full chemical detail can enqueue source enrichment
        self.assertFalse(self.tools["search_chemistry_data"].annotations.read_only_hint)
        self.assertFalse(self.tools["get_chemical"].annotations.read_only_hint)


if __name__ == "__main__":
    unittest.main()
