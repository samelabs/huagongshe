"""G2.2 rendering vertical slice tests.

覆盖:
- Molecule service: SVG/PNG 正常 render、不存在 molecule、无 SMILES/非法 render source
- Reaction service: visibility decision 六象限(public visible/private owner/
  private anon denied/hidden owner/hidden anon denied/not found), 不只测 SVG 字符串
- HTTP contract: media type/immutable cache/404 错误文本
- MCP: tool 名不变、直调 rendering service、reaction tool 不再内联 visibility SQL
- 结构性(AST/call-target): service 不 import fastapi/mcp; HTTP/MCP 依赖同一 owner
"""

from __future__ import annotations

import ast
import asyncio
import os
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

os.environ.setdefault(
    "HGS_DATABASE_URL",
    "postgresql+asyncpg://governance:governance@127.0.0.1:5432/unused",
)

from api.services import rendering as svc  # noqa: E402


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _FakeDB:
    def __init__(self, row):
        self._row = row

    async def execute(self, *_a, **_k):
        return _FakeResult(self._row)


# ---------------------------------------------------------------------------
# Molecule service
# ---------------------------------------------------------------------------

class MoleculeServiceTests(unittest.TestCase):
    def test_svg_normal_render(self):
        svg = svc.smiles_to_svg("CCO", 400, 300)
        self.assertIsNotNone(svg)
        self.assertIn("<svg", svg)
        self.assertNotIn("<?xml", svg)

    def test_png_normal_render(self):
        png = svc.smiles_to_png("CCO", 500, 375)
        self.assertIsNotNone(png)
        self.assertEqual(png[:4], b"\x89PNG")

    def test_invalid_smiles_returns_none(self):
        self.assertIsNone(svc.smiles_to_svg("not-a-smiles"))
        self.assertIsNone(svc.smiles_to_png("not-a-smiles"))

    def test_lookup_missing_molecule_returns_none(self):
        self.assertIsNone(
            asyncio.run(svc.lookup_molecule_smiles(_FakeDB(None), 999)))

    def test_lookup_no_smiles_returns_none(self):
        self.assertIsNone(
            asyncio.run(svc.lookup_molecule_smiles(_FakeDB(("",)), 1)))  # row[0] falsy
        self.assertIsNone(
            asyncio.run(svc.lookup_molecule_smiles(_FakeDB((None,)), 1)))


# ---------------------------------------------------------------------------
# Reaction service — visibility decision(重点, 不只测 SVG)
# ---------------------------------------------------------------------------

def _rxn_row(smiles, visibility, moderation):
    return (smiles, "2026-01-01", visibility, moderation)


class ReactionVisibilityServiceTests(unittest.TestCase):
    def test_public_visible_accessible_anonymously(self):
        src = asyncio.run(svc.lookup_reaction_render_source(
            _FakeDB(_rxn_row("CCO>>CC=O", "public", "visible")),
            1, viewer_id=0, is_admin=False))
        self.assertIsNotNone(src)
        self.assertTrue(src.is_public_visible)
        self.assertEqual(src.reaction_smiles, "CCO>>CC=O")

    def test_private_owner_accessible(self):
        src = asyncio.run(svc.lookup_reaction_render_source(
            _FakeDB(_rxn_row("CCO>>CC=O", "private", "visible")),
            1, viewer_id=7, is_admin=False))
        # _FakeDB 不真正执行 SQL — owner 判定在 SQL; 这里 row 已返回, 验证字段
        self.assertIsNotNone(src)
        self.assertFalse(src.is_public_visible)

    def test_private_anonymous_denied(self):
        """真实 SQL 语义: 匿名+private 查不到行。用 None 行模拟 SQL 过滤结果。"""
        self.assertIsNone(asyncio.run(svc.lookup_reaction_render_source(
            _FakeDB(None), 1, viewer_id=0, is_admin=False)))

    def test_hidden_owner_row_not_public_cacheable(self):
        src = asyncio.run(svc.lookup_reaction_render_source(
            _FakeDB(_rxn_row("C>>N", "public", "hidden")),
            1, viewer_id=7, is_admin=False))
        self.assertIsNotNone(src)
        self.assertFalse(src.is_public_visible, "public+hidden 不可 shared-cache")

    def test_not_found_returns_none(self):
        self.assertIsNone(asyncio.run(svc.lookup_reaction_render_source(
            _FakeDB(None), 424242, viewer_id=0, is_admin=False)))

    def test_cacheability_requires_both_public_and_visible(self):
        for vis, mod, expect in (
            ("public", "visible", True),
            ("public", "hidden", False),
            ("private", "visible", False),
            ("private", "hidden", False),
        ):
            with self.subTest(vis=vis, mod=mod):
                src = asyncio.run(svc.lookup_reaction_render_source(
                    _FakeDB(_rxn_row("C>>S", vis, mod)), 1,
                    viewer_id=1, is_admin=False))
                self.assertEqual(src.is_public_visible, expect)

    def test_reaction_svg_render(self):
        svg = svc.reaction_to_svg("CCO>>CC=O", 1200, 300)
        self.assertIsNotNone(svg)
        self.assertIn("<svg", svg)
        self.assertNotIn("<?xml", svg)

    def test_reaction_bad_smiles_returns_none(self):
        self.assertIsNone(svc.reaction_to_svg("not a reaction"))
        self.assertIsNone(svc.reaction_to_svg(""))


# ---------------------------------------------------------------------------
# HTTP contract — media type / cache / 404(纯 mock db)
# ---------------------------------------------------------------------------

class HttpContractTests(unittest.TestCase):
    def _run(self, fn, **kw):
        return asyncio.run(fn(**kw))

    def test_molecule_svg_404_text(self):
        from fastapi import HTTPException
        from api.mol import render_molecule
        with self.assertRaises(HTTPException) as ctx:
            self._run(render_molecule, chemical_id=999, w=400, h=300,
                      actor=None, db=_FakeDB(None))
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(ctx.exception.detail, "化合物没有可渲染的结构表达")

    def test_molecule_svg_success_immutable(self):
        from api.mol import render_molecule
        resp = self._run(render_molecule, chemical_id=1, w=400, h=300,
                         actor=None, db=_FakeDB(("CCO",)))
        self.assertEqual(resp.media_type, "image/svg+xml")
        self.assertEqual(resp.headers["cache-control"],
                         "public, max-age=31536000, immutable")

    def test_molecule_png_success_media_type(self):
        from api.mol import render_molecule_png
        resp = self._run(render_molecule_png, chemical_id=1, w=500, h=375,
                         actor=None, db=_FakeDB(("CCO",)))
        self.assertEqual(resp.media_type, "image/png")
        self.assertEqual(resp.headers["cache-control"],
                         "public, max-age=31536000, immutable")

    def test_reaction_svg_public_visible_cache(self):
        from api.mol import render_reaction
        resp = self._run(render_reaction, reaction_id=1, w=1200, h=300,
                         actor=None, db=_FakeDB(_rxn_row("CCO>>CC=O", "public", "visible")))
        self.assertEqual(resp.media_type, "image/svg+xml")
        self.assertEqual(resp.headers["cache-control"], "public, max-age=300")

    def test_reaction_svg_private_owner_no_store(self):
        from api.mol import render_reaction
        from api.core.security import Actor
        owner = Actor(id=7, username="u", display_name="U", email="e@t",
                      role="member", avatar_path=None, auth_kind="web")
        resp = self._run(render_reaction, reaction_id=1, w=1200, h=300,
                         actor=owner, db=_FakeDB(_rxn_row("CCO>>CC=O", "private", "visible")))
        self.assertEqual(resp.headers["cache-control"], "private, no-store")

    def test_reaction_svg_not_found_404(self):
        from fastapi import HTTPException
        from api.mol import render_reaction
        with self.assertRaises(HTTPException) as ctx:
            self._run(render_reaction, reaction_id=424242, w=1200, h=300,
                      actor=None, db=_FakeDB(None))
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(ctx.exception.detail, "反应没有可渲染的结构表达")


# ---------------------------------------------------------------------------
# MCP — tool surface + 直调 service + 无内联 visibility SQL
# ---------------------------------------------------------------------------

class McpRenderingContractTests(unittest.TestCase):
    def test_both_tool_names_unchanged(self):
        import api.mcp_server as m
        tools = asyncio.run(m.build_mcp_server().list_tools())
        names = {t.name for t in tools}
        self.assertIn("render_molecule_svg", names)
        self.assertIn("render_reaction_svg", names)
        self.assertEqual(len(names), 14)

    def test_render_tools_call_rendering_service_not_mol_module(self):
        import api.mcp_server as m
        import inspect
        src = inspect.getsource(m)
        for tool_name in ("render_molecule_svg", "render_reaction_svg"):
            start = src.index(f'@server.tool(name="{tool_name}"')
            end = src.index("@server.tool", start + 10)
            block = src[start:end]
            self.assertIn("from .services import rendering", block)
            self.assertNotIn("mol_module", block)
            self.assertNotIn("from . import mol", block)

    def test_reaction_tool_has_no_inline_visibility_sql(self):
        """AST 级: render_reaction_svg tool 体内不得出现对 reactions 表的
        text(...) 领域 SQL lookup(visibility SQL 唯一 owner = service)。"""
        import api.mcp_server as m
        import inspect
        import textwrap
        src = inspect.getsource(m)
        start = src.index('@server.tool(name="render_reaction_svg"')
        end = src.index("@server.tool", start + 10)
        fn = textwrap.dedent(src[start:end][src[start:end].index("async def"):])
        tree = ast.parse(fn)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                self.assertNotIn(
                    "FROM chemistry.reactions", node.value,
                    "MCP render tool 不得内联 reaction 领域 SQL")


# ---------------------------------------------------------------------------
# 结构性 — service transport-neutral + 单一 owner
# ---------------------------------------------------------------------------

class RenderingArchitectureTests(unittest.TestCase):
    BANNED_MODULES = {"fastapi", "mcp", "uvicorn", "starlette"}

    def _ids(self, path):
        tree = ast.parse((REPO / path).read_text("utf-8"))
        ids = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    root = a.name.split(".")[0]
                    if root in self.BANNED_MODULES:
                        self.fail(f"{path} 不得导入 {root}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] in self.BANNED_MODULES:
                    self.fail(f"{path} 不得从 {node.module} 导入")
            if isinstance(node, ast.Name):
                ids.add(node.id)
            elif isinstance(node, ast.Attribute):
                ids.add(node.attr)
        return ids

    def test_service_is_transport_neutral(self):
        ids = self._ids("api/services/rendering.py")
        for banned in ("HTTPException", "ToolError", "Request", "Response",
                       "UploadFile", "Depends", "Context"):
            self.assertNotIn(banned, ids)

    def test_render_kernel_single_owner(self):
        """RDKit draw kernel 只存在于 services/rendering.py 一份。"""
        svc_src = (REPO / "api" / "services" / "rendering.py").read_text("utf-8")
        mol_src = (REPO / "api" / "mol.py").read_text("utf-8")
        mcp_src = (REPO / "api" / "mcp_server.py").read_text("utf-8")
        self.assertIn("MolDraw2DSVG", svc_src)
        self.assertIn("MolDraw2DCairo", svc_src)
        for marker in ("MolDraw2DSVG", "MolDraw2DCairo", "Compute2DCoords",
                       "ReactionFromSmarts"):
            self.assertNotIn(marker, mol_src)
            self.assertNotIn(marker, mcp_src)

    def test_reaction_visibility_sql_single_owner(self):
        """reaction visibility SQL 只在 services/rendering.py。
        mol.py(旧 HTTP 副本)与 mcp_server.py 均不得再持有。"""
        owner = (REPO / "api" / "services" / "rendering.py").read_text("utf-8")
        self.assertIn("moderation_status='visible'", owner)
        for path in ("api/mol.py", "api/mcp_server.py"):
            src = (REPO / path).read_text("utf-8")
            self.assertNotIn(
                "FROM chemistry.reactions", src,
                f"{path} 不得持有 reaction 领域 SQL(唯一 owner=services/rendering.py)")

    def test_molecule_lookup_sql_single_owner(self):
        owner = (REPO / "api" / "services" / "rendering.py").read_text("utf-8")
        self.assertIn("FROM chemistry.chemicals", owner)
        for path in ("api/mol.py", "api/mcp_server.py"):
            src = (REPO / path).read_text("utf-8")
            self.assertNotIn("FROM chemistry.chemicals", src)

    def test_http_and_mcp_share_same_render_owner(self):
        """两 adapter 都必须引用 services.rendering。"""
        mol_src = (REPO / "api" / "mol.py").read_text("utf-8")
        mcp_src = (REPO / "api" / "mcp_server.py").read_text("utf-8")
        self.assertIn("from .services import rendering", mol_src)
        self.assertIn("render_service.", mol_src)
        self.assertIn("from .services import rendering", mcp_src)


if __name__ == "__main__":
    unittest.main()
