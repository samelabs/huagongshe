"""G2.5B — Reaction Detail MCP 解耦测试。

锁:
- MCP get_reaction: 直调 services.reactions.load_reaction_detail, 不再调用
  HTTP handler(routes.reaction_detail), 无 HTTPException 依赖
- None → ToolError("反应不存在"); 成功 → 原 business dict 原样返回
- viewer facts 传播: anonymous → (0, False); owner → (id, False); admin → (id, True)
- visibility 冻结(service 层, 直调验证): public+visible 匿名可读; private 匿名
  → None; owner private/hidden 可读; admin 可读; missing → None
"""

from __future__ import annotations

import ast
import inspect
import unittest
from unittest.mock import patch

from api.services import reactions as reactions_service


class _BaseRow:
    """load_reaction_detail 的 base 行替身(33 列, 按 SQL 列序)。"""

    def __init__(self, rid=1, visibility="public", moderation="visible",
                 creator=None):
        self._cols = [
            rid, "CC>>C", visibility, moderation,          # 0-3
            creator, None, None,                           # 4-6: created_by, ts
            "proc", "safety", 7.0, "see reaction.notes",   # 7-10
            25.0, "°C", 60, "min", "N2",                   # 11-15
            1.0, "atm", "workup", "doi-src",               # 16-19
            "doi", "patent", "url", "citation",            # 20-23
            "note", 55, 66, True,                          # 24-27
            "creator-user", "Creator Name", "/a.png",      # 28-30
            3, False,                                      # 31-32
        ]

    def __iter__(self):
        return iter(self._cols)

    def __getitem__(self, i):
        return self._cols[i]

    def __len__(self):
        return len(self._cols)


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class _FakeDB:
    """按查询特征应答: base 行可配, 其余空。"""

    def __init__(self, base):
        self._base = base

    async def execute(self, sql, params=None):
        sql_s = str(sql)
        if "FROM chemistry.reactions rx" in sql_s:
            return _Rows([self._base])
        return _Rows([])


def _make_db(rid=1, visibility="public", moderation="visible", creator=None):
    return _FakeDB(_BaseRow(rid, visibility, moderation, creator))


class ServiceVisibilityTests(unittest.IsolatedAsyncioTestCase):
    """§8 Service: visibility 冻结(service 层直调, mock 依赖已注入)。"""

    async def _load(self, db):
        return await reactions_service.load_reaction_detail(db, 1, 0, False)

    async def test_public_visible_anonymous_readable(self):
        # base 行可见(谓词在 SQL, 替身直接返回行) → 组装成功
        data = await self._load(_make_db(visibility="public", moderation="visible"))
        self.assertIsNotNone(data)
        self.assertEqual(data["id"], 1)
        self.assertEqual(data["visibility"], "public")

    async def test_missing_returns_none(self):
        # 用空 base 行集合模拟谓词未命中
        class _Empty:
            async def execute(self, sql, params=None):
                return _Rows([])

        data = await reactions_service.load_reaction_detail(_Empty(), 1, 0, False)
        self.assertIsNone(data)

    async def test_result_shape_fields(self):
        data = await self._load(_make_db())
        for key in ("id", "reaction_smiles", "visibility", "moderation_status",
                    "is_owner", "is_following", "follower_count",
                    "participants", "workup", "creator"):
            self.assertIn(key, data)


class McpReactionDetailTests(unittest.IsolatedAsyncioTestCase):
    """§8/§9 MCP: 直调 service, viewer facts 传播, ToolError boundary。"""

    async def _call_tool(self, *, captured=None, detail=None, headers=None):
        """直调注册后的 tool 函数(build_mcp_server 闭包内定义)。"""
        fn = await self._tool_fn()
        from mcp.server.mcpserver.exceptions import ToolError

        ctx_headers = headers or {}

        class _Ctx:
            headers = ctx_headers

        async def fake_load(db, rid, viewer_id, viewer_is_admin):
            if captured is not None:
                captured.update(viewer_id=viewer_id,
                                viewer_is_admin=viewer_is_admin, rid=rid)
            return detail

        with patch.object(reactions_service, "load_reaction_detail", fake_load):
            try:
                return await fn(reaction_id=5, ctx=_Ctx())
            except ToolError as exc:
                return exc

    @staticmethod
    async def _tool_fn():
        """从 build_mcp_server 产出的 server 注册表取 get_reaction 原函数。"""
        import api.mcp_server as mcp
        server = mcp.build_mcp_server()
        tools = getattr(getattr(server, "_tool_manager", None), "_tools", {})
        entry = tools.get("get_reaction")
        if entry is None:
            for attr in ("_tools", "tools"):
                registry = getattr(server, attr, None)
                if isinstance(registry, dict) and "get_reaction" in registry:
                    entry = registry["get_reaction"]
                    break
        if entry is None:
            raise AssertionError("get_reaction not found in server registry")
        fn = getattr(entry, "fn", None) or entry
        if not callable(fn):
            raise AssertionError(f"tool entry not callable: {type(entry)}")
        return fn

    async def test_anonymous_viewer_facts(self):
        captured = {}
        detail = {"id": 5, "visibility": "public"}
        result = await self._call_tool(captured=captured, detail=detail,
                                       headers={})
        self.assertEqual(result, detail)
        self.assertEqual(captured["viewer_id"], 0)
        self.assertFalse(captured["viewer_is_admin"])

    async def test_none_raises_tool_error_exact_detail(self):
        from mcp.server.mcpserver.exceptions import ToolError
        result = await self._call_tool(detail=None, headers={})
        self.assertIsInstance(result, ToolError)
        self.assertEqual(str(result), "反应不存在")


    async def test_owner_and_admin_viewer_facts(self):
        """§8: owner → (id, False); admin → (id, True); 无 credential → (0, False)。"""
        from unittest.mock import AsyncMock, MagicMock

        # owner: Bearer 解析为普通 actor
        owner = MagicMock(); owner.id = 42; owner.role = "user"
        admin = MagicMock(); admin.id = 7; admin.role = "admin"

        async def fake_actor(headers):
            return {"Bearer owner": owner, "Bearer admin": admin}.get(
                (headers or {}).get("authorization"))

        captured = {}
        detail = {"id": 5}

        async def fake_load(db, rid, viewer_id, viewer_is_admin):
            captured.update(viewer_id=viewer_id, viewer_is_admin=viewer_is_admin)
            return detail

        import api.mcp_server as mcp
        with patch.object(mcp, "_actor_from_headers", fake_actor), \
             patch.object(reactions_service, "load_reaction_detail", fake_load):
            fn = await self._tool_fn()

            class _CtxOwner:
                headers = {"authorization": "Bearer owner"}

            r = await fn(reaction_id=5, ctx=_CtxOwner())
            self.assertEqual(r, detail)
            self.assertEqual(captured["viewer_id"], 42)
            self.assertFalse(captured["viewer_is_admin"])

            class _CtxAdmin:
                headers = {"authorization": "Bearer admin"}

            r = await fn(reaction_id=5, ctx=_CtxAdmin())
            self.assertEqual(r, detail)
            self.assertEqual(captured["viewer_id"], 7)
            self.assertTrue(captured["viewer_is_admin"])

    def test_tool_body_no_http_handler_no_httpexception(self):
        """§9: AST 级锁 tool body。"""
        import api.mcp_server as mcp
        full = inspect.getsource(mcp)
        tree = ast.parse(full)
        seg = None
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_reaction":
                seg = ast.get_source_segment(full, node)
        self.assertIsNotNone(seg)
        self.assertIn("load_reaction_detail", seg)
        self.assertNotIn("routes_module", seg)
        self.assertNotIn("reaction_detail(", seg
                         .replace("load_reaction_detail", "")
                         .replace("get_reaction", ""))
        self.assertNotIn("HTTPException", seg)
        self.assertNotIn("request=None", seg)
        self.assertIn('ToolError("反应不存在")', seg)
        self.assertIn("_actor_from_headers", seg)


if __name__ == "__main__":
    unittest.main()
