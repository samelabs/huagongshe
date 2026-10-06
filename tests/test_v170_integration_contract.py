"""Cross-domain v1.7.0 integration contract.

This test exists on the combined integration line to prove that adding Notes
does not silently expand or couple the frozen MCP tool surface.
"""

from __future__ import annotations

import asyncio
import ast
import os
import unittest
from pathlib import Path

os.environ.setdefault(
    "HGS_DATABASE_URL",
    "postgresql+asyncpg://integration:integration@127.0.0.1:5432/unused",
)

from api.mcp_server import build_mcp_server

REPO = Path(__file__).resolve().parents[1]


class V170IntegrationContractTests(unittest.TestCase):
    def test_notes_exist_without_expanding_mcp_surface(self):
        tools = {
            tool.name for tool in asyncio.run(build_mcp_server().list_tools())
        }
        self.assertEqual(len(tools), 13)
        self.assertFalse(any("note" in name.lower() for name in tools))
        self.assertTrue((REPO / "api/services/notes.py").exists())
        self.assertTrue(
            (REPO / "web/components/workbench/panels/NotesPanel.tsx").exists()
        )

    def test_notes_service_remains_transport_neutral(self):
        tree = ast.parse(
            (REPO / "api/services/notes.py").read_text(encoding="utf-8")
        )
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
        self.assertFalse(any(name.startswith("mcp") for name in imports))
        self.assertFalse(any(name.startswith("fastapi") for name in imports))

    def test_prd_keeps_note_mcp_out_of_scope(self):
        prd = (REPO / "docs/PRD_V1.7.0.md").read_text(encoding="utf-8")
        self.assertIn("does not add Note MCP tools", prd)
        self.assertIn("No `note:write` in v1.7.0", prd)


if __name__ == "__main__":
    unittest.main()
