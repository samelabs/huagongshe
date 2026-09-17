"""G2.5C — My Reactions List 共享 service 测试。

锁:
- services/reactions.list_my_reactions: bounded UNION ALL(all 分支) vs 单
  分支 SQL 选择、counts 只统计 owner 全量、empty 正常返回、offset 计算
- service transport-neutral(FastAPI/HTTPException/ToolError = 0)
- HTTP adapter: 只余 validation+调用, 无 SQL/offset/counts/transformation
- MCP adapter: 直调 service, clamp 保持, 无 reactions_module.my_reactions
"""

from __future__ import annotations

import ast
import inspect
import unittest
from unittest.mock import patch

from api.services import reactions as reactions_service


class _Mapping(dict):
    pass


class _MappingsResult:
    def __init__(self, rows):
        self._rows = [_Mapping(r) for r in rows]

    def all(self):
        return self._rows


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeDB:
    """按查询特征应答: owned(UNION)/单分支/counts。"""

    def __init__(self, items=(), counts=()):
        self._items = list(items)
        self._counts = list(counts)

    async def execute(self, sql, params=None):
        sql_s = str(sql)
        if "GROUP BY visibility" in sql_s:
            return _Result(self._counts)
        # rows 查询: 真实 SQLAlchemy result.mappings().all() 语义
        res = _MappingsResult(self._items)
        res.mappings = lambda: res
        return res


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_branch_uses_bounded_union_sql(self):
        db = _FakeDB()
        captured = {}

        class _SpyDB(_FakeDB):
            async def execute(self, sql, params=None):
                key = "counts" if "GROUP BY visibility" in str(sql) else "items"
                captured[key] = {"sql": str(sql), "params": dict(params or {})}
                return await super().execute(sql, params)

        await reactions_service.list_my_reactions(
            _SpyDB(), actor_id=9, visibility="all", page=3, page_size=20)
        items_q = captured["items"]
        self.assertIn("WITH owned AS MATERIALIZED", items_q["sql"])
        self.assertIn("LIMIT :window", items_q["sql"])
        self.assertEqual(items_q["params"]["window"], 60)  # offset 40+20
        self.assertEqual(items_q["params"]["offset"], 40)
        self.assertEqual(items_q["params"]["user_id"], 9)
        # counts 查询不带 visibility/page(全量语义)
        counts_q = captured["counts"]
        self.assertEqual(counts_q["params"], {"user_id": 9})

    async def test_single_branch_sql_and_result_assembly(self):
        db = _FakeDB(
            items=[{"id": 5, "reaction_smiles": "C>>CC", "visibility": "public",
                    "moderation_status": "visible", "created_at": "t1",
                    "updated_at": "t2", "followers": 3}],
            counts=[("public", 4), ("private", 2)])
        result = await reactions_service.list_my_reactions(
            db, actor_id=9, visibility="public", page=1, page_size=20)
        self.assertEqual(result["items"][0]["id"], 5)
        self.assertEqual(result["items"][0]["followers"], 3)
        self.assertEqual(result["counts"], {"public": 4, "private": 2, "all": 6})
        self.assertEqual(result["page"], 1)
        self.assertEqual(result["page_size"], 20)

    async def test_empty_returns_normal_empty_items(self):
        result = await reactions_service.list_my_reactions(
            _FakeDB(), actor_id=9, visibility="private", page=1, page_size=20)
        self.assertEqual(result["items"], [])
        self.assertEqual(result["counts"], {"public": 0, "private": 0, "all": 0})

    async def test_counts_missing_visibility_defaults_zero(self):
        result = await reactions_service.list_my_reactions(
            _FakeDB(counts=[("public", 7)]), actor_id=9,
            visibility="all", page=1, page_size=20)
        self.assertEqual(result["counts"], {"public": 7, "private": 0, "all": 7})

    def test_service_transport_neutral(self):
        source = inspect.getsource(reactions_service)
        for token in ("fastapi", "HTTPException", "ToolError",
                      "Request", "Response", "Context"):
            self.assertNotIn(token, source)
        # AST 级 import 图
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom) and node.module:
                self.assertNotIn("fastapi", node.module)
                self.assertNotIn("mcp", node.module)


class AdapterTests(unittest.TestCase):
    def test_http_adapter_has_no_sql_or_offset(self):
        from api import reactions as reactions_api
        source = inspect.getsource(reactions_api.my_reactions)
        self.assertIn("list_my_reactions(", source)
        for token in ("WITH owned", "OFFSET", "GROUP BY visibility",
                      "offset =", "counts"):
            self.assertNotIn(token, source)

    def test_mcp_adapter_calls_service_not_http(self):
        import api.mcp_server as mcp
        full = inspect.getsource(mcp)
        tree = ast.parse(full)
        seg = None
        for node in ast.walk(tree):
            if (isinstance(node, ast.AsyncFunctionDef)
                    and node.name == "list_my_reactions"):
                seg = ast.get_source_segment(full, node)
        self.assertIsNotNone(seg)
        self.assertNotIn("reactions_module", seg)
        self.assertNotIn("my_reactions(", seg.replace(
            "list_my_reactions", "").replace("_list_service", "x"))
        self.assertIn("min(max(page, 1), 500)", seg)
        self.assertIn("min(max(page_size, 1), 50)", seg)
        self.assertIn("ToolError", seg)  # visibility validation 保持


if __name__ == "__main__":
    unittest.main()
