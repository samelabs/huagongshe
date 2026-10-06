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


    async def test_visibility_private_branch_sql(self):
        db = _FakeDB()
        captured = {}

        class _SpyDB(_FakeDB):
            async def execute(self, sql, params=None):
                key = "counts" if "GROUP BY visibility" in str(sql) else "items"
                captured[key] = {"sql": str(sql), "params": dict(params or {})}
                return await super().execute(sql, params)

        await reactions_service.list_my_reactions(
            _SpyDB(), actor_id=3, visibility="private", page=1, page_size=10)
        q = captured["items"]["sql"]
        # 单分支: 不走 UNION, visibility 走绑定参数
        self.assertNotIn("UNION ALL", q)
        self.assertIn("r.visibility=:visibility", q)
        self.assertEqual(captured["items"]["params"]["visibility"], "private")
        self.assertEqual(captured["items"]["params"]["limit"], 10)
        self.assertEqual(captured["items"]["params"]["offset"], 0)

    async def test_ordering_id_desc_in_both_branches(self):
        for vis in ("all", "public"):
            captured = {}

            class _SpyDB(_FakeDB):
                async def execute(self, sql, params=None):
                    key = "counts" if "GROUP BY visibility" in str(sql) else "items"
                    captured[key] = str(sql)
                    return await super().execute(sql, params)

            await reactions_service.list_my_reactions(
                _SpyDB(), actor_id=1, visibility=vis, page=1, page_size=10)
            self.assertRegex(captured["items"], r"ORDER BY (?:r\.)?id DESC")

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



class HttpAdapterTests(unittest.IsolatedAsyncioTestCase):
    """§18: handler 调 service 一次、参数逐项正确、empty 正常 200。"""

    async def test_handler_passes_actor_and_params_to_service(self):
        from unittest.mock import MagicMock

        from api import reactions as reactions_api
        actor = MagicMock(); actor.id = 77
        captured = {}

        async def fake_service(db, *, actor_id, visibility, page, page_size):
            captured.update(actor_id=actor_id, visibility=visibility,
                            page=page, page_size=page_size, calls=1)
            return {"items": [], "counts": {"public": 0, "private": 0, "all": 0},
                    "page": page, "page_size": page_size}

        with patch.object(reactions_api, "list_my_reactions", fake_service):
            result = await reactions_api.my_reactions(
                visibility="public", page=2, page_size=15,
                actor=actor, db=object())
        self.assertEqual(captured["actor_id"], 77)
        self.assertEqual(captured["visibility"], "public")
        self.assertEqual(captured["page"], 2)
        self.assertEqual(captured["page_size"], 15)
        self.assertEqual(captured["calls"], 1)  # service 被调用一次
        self.assertEqual(result["items"], [])

    def test_http_validation_contract_unchanged(self):
        """§18: 422 由 FastAPI Query/Literal validation 保障(签名冻结)。"""
        from api import reactions as reactions_api
        import inspect
        sig = inspect.signature(reactions_api.my_reactions)
        self.assertIn("visibility", sig.parameters)
        self.assertIn("page", sig.parameters)
        self.assertIn("page_size", sig.parameters)
        # Query constraint 留在签名(源码级)
        src = inspect.getsource(reactions_api.my_reactions)
        self.assertIn('Query(1, ge=1, le=500)', src)
        self.assertIn('Query(20, ge=1, le=50)', src)
        self.assertIn('Literal["all", "public", "private"]', src)


class McpBehaviorTests(unittest.IsolatedAsyncioTestCase):
    """§19: MCP 行为 — 无 credential ToolError / actor 传播 / clamp / 原样返回。"""

    @staticmethod
    async def _tool_fn():
        import api.mcp_server as mcp
        server = mcp.build_mcp_server()
        tools = getattr(getattr(server, "_tool_manager", None), "_tools", {})
        entry = tools.get("list_my_reactions")
        if entry is None:
            raise AssertionError("list_my_reactions not found in registry")
        fn = getattr(entry, "fn", None) or entry
        if not callable(fn):
            raise AssertionError(f"tool entry not callable: {type(entry)}")
        return fn

    async def _call(self, *, actor="UNSET", captured=None, result=None,
                    headers=None, **kwargs):
        from mcp.server.mcpserver.exceptions import ToolError
        import api.mcp_server as mcp

        class _Ctx:
            def __init__(self):
                self.headers = headers if headers is not None else {}

        if actor == "UNSET":
            async def fake_actor(headers):
                return None
        else:
            async def fake_actor(headers):
                return actor

        async def fake_service(db, *, actor_id, visibility, page, page_size):
            if captured is not None:
                captured.update(actor_id=actor_id, visibility=visibility,
                                page=page, page_size=page_size)
            return result if result is not None else {"items": [], "counts": {},
                                                       "page": page,
                                                       "page_size": page_size}

        from api.services import reactions as svc
        with patch.object(mcp, "_actor_from_headers", fake_actor), \
             patch.object(svc, "list_my_reactions", fake_service):
            try:
                return await (await self._tool_fn())(ctx=_Ctx(), **kwargs)
            except ToolError as exc:
                return exc

    async def test_no_credential_returns_oauth_challenge(self):
        from mcp.types import CallToolResult
        r = await self._call(actor=None)
        self.assertIsInstance(r, CallToolResult)
        self.assertTrue(r.is_error)
        meta = r.meta or {}
        challenge = meta.get("mcp/www_authenticate") or []
        self.assertTrue(challenge)
        self.assertIn('scope="read"', challenge[0])

    async def test_actor_id_and_params_propagated(self):
        from unittest.mock import MagicMock
        actor = MagicMock(); actor.id = 4242; actor.auth_kind = "agent"; actor.scopes = []
        captured = {}
        svc_result = {"items": [{"id": 1}], "counts": {"all": 1},
                      "page": 1, "page_size": 20}
        r = await self._call(actor=actor, captured=captured,
                             result=svc_result,
                             visibility="private", page=3, page_size=25)
        self.assertEqual(r, svc_result)  # 原 dict 原样返回
        self.assertEqual(captured["actor_id"], 4242)
        self.assertEqual(captured["visibility"], "private")
        self.assertEqual(captured["page"], 3)
        self.assertEqual(captured["page_size"], 25)

    async def test_invalid_visibility_tool_error(self):
        from mcp.server.mcpserver.exceptions import ToolError
        from unittest.mock import MagicMock
        actor = MagicMock(); actor.id = 1; actor.auth_kind = "agent"; actor.scopes = []
        r = await self._call(actor=actor, visibility="secret")
        self.assertIsInstance(r, ToolError)
        self.assertIn("visibility", str(r))

    async def test_page_clamp_both_directions(self):
        from unittest.mock import MagicMock
        actor = MagicMock(); actor.id = 1; actor.auth_kind = "agent"; actor.scopes = []
        captured = {}
        await self._call(actor=actor, captured=captured, page=0)
        self.assertEqual(captured["page"], 1)
        await self._call(actor=actor, captured=captured, page=99999)
        self.assertEqual(captured["page"], 500)

    async def test_page_size_clamp_both_directions(self):
        from unittest.mock import MagicMock
        actor = MagicMock(); actor.id = 1; actor.auth_kind = "agent"; actor.scopes = []
        captured = {}
        await self._call(actor=actor, captured=captured, page_size=0)
        self.assertEqual(captured["page_size"], 1)
        await self._call(actor=actor, captured=captured, page_size=999)
        self.assertEqual(captured["page_size"], 50)

    async def test_no_http_exception_leakage(self):
        """§19: tool body 无 HTTPException import/raise。"""
        import api.mcp_server as mcp
        import inspect as _i
        full = _i.getsource(mcp)
        import ast as _ast
        for node in _ast.walk(_ast.parse(full)):
            if (isinstance(node, _ast.AsyncFunctionDef)
                    and node.name == "list_my_reactions"):
                seg = _ast.get_source_segment(full, node)
        self.assertIsNotNone(seg)
        self.assertNotIn("HTTPException", seg)
        self.assertNotIn("reactions_module", seg)
        self.assertNotIn("request=None", seg)


if __name__ == "__main__":
    unittest.main()
