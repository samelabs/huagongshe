"""G2.6B — Skill List 共享 service 测试(skill.query.list kernel)。

锁:
- public/mine 共用同一 query implementation, 仅 selector predicate 不同
- q/category filter(ILIKE 三列/精确)、组合
- ORDER BY s.updated_at DESC, s.id DESC;offset=(page-1)*page_size
- count 查询/13 字段 items+owner 子对象/response shape
- transport-neutral(AST 级)
- HTTP adapter 无 SQL;MCP 直调 service, truncate/clamp/401/ToolError 语义不变
"""

from __future__ import annotations

import ast
import inspect
import unittest
from unittest.mock import MagicMock, patch

from api.services import skills as skills_service


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class _MappingsRow(dict):
    pass


class _MappingsResult:
    def __init__(self, rows):
        self._rows = [_MappingsRow(r) for r in rows]

    def all(self):
        return self._rows


def _row(**over):
    base = {
        "id": 1, "slug": "demo", "title": "Demo", "description": "d",
        "category": "chem", "origin": "user", "visibility": "public",
        "has_scripts": False, "file_count": 3, "size_bytes": 100,
        "updated_at": "2026-01-01", "username": "u1", "display_name": "U1",
    }
    base.update(over)
    return base


class _FakeDB:
    def __init__(self, total=0, rows=None):
        self._total = total
        self._rows = rows or []
        self.calls = []

    async def execute(self, sql, params=None):
        sql_s = str(sql)
        self.calls.append({"sql": sql_s, "params": dict(params or {})})
        if "count(*)" in sql_s:
            return _FakeResult(self._total)
        res = _MappingsResult(self._rows)
        res.mappings = lambda: res
        return res


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_selector_predicate(self):
        db = _FakeDB()
        await skills_service.list_skills(
            db, scope="public", owner_id=None, q="", category="",
            page=1, page_size=30)
        for c in db.calls:
            self.assertIn("s.visibility='public'", c["sql"])
            self.assertNotIn("s.owner_id=:owner", c["sql"])

    async def test_mine_selector_predicate_and_owner_param(self):
        db = _FakeDB()
        await skills_service.list_skills(
            db, scope="mine", owner_id=42, q="", category="",
            page=1, page_size=30)
        for c in db.calls:
            self.assertIn("s.owner_id=:owner", c["sql"])
            self.assertNotIn("s.visibility='public'", c["sql"])
            self.assertEqual(c["params"]["owner"], 42)

    async def test_public_and_mine_share_same_query_implementation(self):
        """G1 kernel 物理实现: 两 scope 走同一函数同一 SQL 模板。"""
        dbs = []
        for scope, owner in (("public", None), ("mine", 7)):
            db = _FakeDB()
            await skills_service.list_skills(
                db, scope=scope, owner_id=owner, q="x", category="c",
                page=2, page_size=10)
            dbs.append(db)
        for c0, c1 in zip(dbs[0].calls, dbs[1].calls):
            # 同序查询(count→rows), 除 selector/owner 参数外 SQL 结构相同
            self.assertEqual(c0["sql"].replace("s.visibility='public'", "SEL"),
                             c1["sql"].replace("s.owner_id=:owner", "SEL"))

    async def test_q_filter_ilike_three_columns(self):
        db = _FakeDB()
        await skills_service.list_skills(
            db, scope="public", owner_id=None, q="醇", category="",
            page=1, page_size=30)
        for c in db.calls:
            self.assertIn(
                "(s.slug ILIKE :q OR s.title ILIKE :q OR s.description ILIKE :q)",
                c["sql"])
            self.assertEqual(c["params"]["q"], "%醇%")

    async def test_category_filter_exact(self):
        db = _FakeDB()
        await skills_service.list_skills(
            db, scope="public", owner_id=None, q="", category=" 有机 ",
            page=1, page_size=30)
        for c in db.calls:
            self.assertIn("s.category=:category", c["sql"])
            self.assertEqual(c["params"]["category"], "有机")

    async def test_q_plus_category_combination(self):
        db = _FakeDB()
        await skills_service.list_skills(
            db, scope="public", owner_id=None, q="a", category="b",
            page=1, page_size=30)
        rows_call = db.calls[-1]
        self.assertIn("s.visibility='public'", rows_call["sql"])
        self.assertIn("ILIKE :q", rows_call["sql"])
        self.assertIn("s.category=:category", rows_call["sql"])

    async def test_pagination_offset_limit(self):
        db = _FakeDB()
        await skills_service.list_skills(
            db, scope="public", owner_id=None, q="", category="",
            page=4, page_size=25)
        c = db.calls[-1]
        self.assertEqual(c["params"]["offset"], 75)
        self.assertEqual(c["params"]["limit"], 25)
        self.assertIn("LIMIT :limit OFFSET :offset", c["sql"])

    async def test_ordering_updated_at_desc_id_desc(self):
        db = _FakeDB()
        await skills_service.list_skills(
            db, scope="public", owner_id=None, q="", category="",
            page=1, page_size=30)
        self.assertIn("ORDER BY s.updated_at DESC, s.id DESC", db.calls[-1]["sql"])

    async def test_items_transformation_and_owner_shape(self):
        db = _FakeDB(total=5, rows=[_row(id=9, slug="s9", size_bytes="512",
                                         username="alice", display_name="Alice")])
        result = await skills_service.list_skills(
            db, scope="public", owner_id=None, q="", category="",
            page=1, page_size=30)
        item = result["items"][0]
        self.assertEqual(
            list(item.keys()),
            ["id", "slug", "title", "description", "category", "origin",
             "visibility", "has_scripts", "file_count", "size_bytes",
             "updated_at", "owner"])
        self.assertEqual(item["size_bytes"], 512)  # int() 转换保留
        self.assertEqual(item["owner"], {"username": "alice",
                                         "display_name": "Alice"})

    async def test_count_and_response_shape(self):
        db = _FakeDB(total=12, rows=[_row()])
        result = await skills_service.list_skills(
            db, scope="mine", owner_id=3, q="", category="",
            page=2, page_size=10)
        self.assertEqual(result["total"], 12)
        self.assertEqual(result["page"], 2)
        self.assertEqual(result["page_size"], 10)
        self.assertEqual(len(result["items"]), 1)

    async def test_empty_list(self):
        result = await skills_service.list_skills(
            _FakeDB(total=0), scope="public", owner_id=None, q="", category="",
            page=1, page_size=30)
        self.assertEqual(result["items"], [])
        self.assertEqual(result["total"], 0)

    def test_service_transport_neutral(self):
        source = inspect.getsource(skills_service)
        for token in ("fastapi", "starlette", "HTTPException", "ToolError",
                      "UploadFile", "Request", "Response"):
            self.assertNotIn(token, source)
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom) and node.module:
                self.assertFalse(node.module.startswith(("fastapi", "starlette",
                                                         "mcp")))


class HttpAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_anonymous_passes_owner_none(self):
        from api import skills as skills_api
        captured = {}

        async def fake(db, *, scope, owner_id, q, category, page, page_size):
            captured.update(scope=scope, owner_id=owner_id)
            return {"total": 0, "items": []}

        with patch.object(skills_api, "list_skills_service", fake):
            await skills_api.list_skills(scope="public", q="", category="",
                                         page=1, page_size=30,
                                         actor=None, db=object())
        self.assertEqual(captured["owner_id"], None)

    async def test_public_actor_still_public_scope(self):
        from api import skills as skills_api
        captured = {}

        async def fake(db, *, scope, owner_id, q, category, page, page_size):
            captured.update(scope=scope, owner_id=owner_id)
            return {"total": 0, "items": []}

        actor = MagicMock(); actor.id = 55
        with patch.object(skills_api, "list_skills_service", fake):
            await skills_api.list_skills(scope="public", q="", category="",
                                         page=1, page_size=30,
                                         actor=actor, db=object())
        # actor 存在不增强 public selector
        self.assertEqual(captured["scope"], "public")
        self.assertEqual(captured["owner_id"], None)

    async def test_mine_actor_id_passed(self):
        from api import skills as skills_api
        captured = {}

        async def fake(db, *, scope, owner_id, q, category, page, page_size):
            captured.update(scope=scope, owner_id=owner_id)
            return {"total": 0, "items": []}

        actor = MagicMock(); actor.id = 88
        with patch.object(skills_api, "list_skills_service", fake):
            await skills_api.list_skills(scope="mine", q="", category="",
                                         page=1, page_size=30,
                                         actor=actor, db=object())
        self.assertEqual(captured["owner_id"], 88)

    async def test_mine_anonymous_401_exact(self):
        from fastapi import HTTPException
        from api import skills as skills_api
        with self.assertRaises(HTTPException) as ctx:
            await skills_api.list_skills(scope="mine", q="", category="",
                                         page=1, page_size=30,
                                         actor=None, db=object())
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertEqual(ctx.exception.detail, "列出自己的技能需要登录或 API Token")

    def test_http_validation_signature_unchanged(self):
        from api import skills as skills_api
        src = inspect.getsource(skills_api.list_skills)
        self.assertIn('pattern="^(public|mine)$"', src)
        self.assertIn("max_length=120", src)
        self.assertIn("max_length=40", src)
        self.assertIn("Query(1, ge=1, le=500)", src)
        self.assertIn("Query(30, ge=1, le=100)", src)

    def test_http_handler_has_no_sql(self):
        from api import skills as skills_api
        src = inspect.getsource(skills_api.list_skills)
        for token in ("SELECT", "ILIKE", "JOIN", "ORDER BY", "OFFSET"):
            self.assertNotIn(token, src)


class McpAdapterTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    async def _tool_fn():
        import api.mcp_server as mcp
        server = mcp.build_mcp_server()
        tools = getattr(getattr(server, "_tool_manager", None), "_tools", {})
        entry = tools.get("list_skills")
        if entry is None:
            raise AssertionError("list_skills not found in registry")
        fn = getattr(entry, "fn", None) or entry
        if not callable(fn):
            raise AssertionError(f"tool entry not callable: {type(entry)}")
        return fn

    async def _call(self, *, actor="UNSET", captured=None, result=None,
                    headers=None, **kwargs):
        from mcp.server.mcpserver.exceptions import ToolError
        import api.mcp_server as mcp
        ctx_headers = headers if headers is not None else {}

        if actor == "UNSET":
            async def fake_actor(headers):
                return None
        else:
            async def fake_actor(headers):
                return actor

        async def fake_service(db, *, scope, owner_id, q, category,
                               page, page_size):
            if captured is not None:
                captured.update(scope=scope, owner_id=owner_id, q=q,
                                category=category, page=page,
                                page_size=page_size)
            return result if result is not None else {"total": 0, "items": []}

        with patch.object(mcp, "_actor_from_headers", fake_actor), \
             patch.object(skills_service, "list_skills", fake_service):
            try:
                return await (await self._tool_fn())(ctx=type("C", (), {
                    "headers": ctx_headers})(), **kwargs)
            except ToolError as exc:
                return exc

    async def test_public_anonymous_works(self):
        captured = {}
        r = await self._call(actor=None, captured=captured, scope="public")
        self.assertEqual(r, {"total": 0, "items": []})
        self.assertEqual(captured["scope"], "public")
        self.assertIsNone(captured["owner_id"])

    async def test_mine_no_actor_tool_error_exact(self):
        from mcp.server.mcpserver.exceptions import ToolError
        r = await self._call(actor=None, scope="mine")
        self.assertIsInstance(r, ToolError)
        self.assertTrue(str(r).startswith("Authentication required."))

    async def test_mine_actor_id_propagated(self):
        actor = MagicMock(); actor.id = 66
        captured = {}
        await self._call(actor=actor, captured=captured, scope="mine")
        self.assertEqual(captured["owner_id"], 66)
        self.assertEqual(captured["scope"], "mine")

    async def test_invalid_scope_tool_error(self):
        from mcp.server.mcpserver.exceptions import ToolError
        actor = MagicMock(); actor.id = 1
        r = await self._call(actor=actor, scope="wrong")
        self.assertIsInstance(r, ToolError)
        self.assertIn("scope", str(r))

    async def test_q_and_category_truncate(self):
        actor = MagicMock(); actor.id = 1
        captured = {}
        await self._call(actor=actor, captured=captured,
                         q="x" * 300, category="y" * 100)
        self.assertEqual(len(captured["q"]), 120)
        self.assertEqual(len(captured["category"]), 40)

    async def test_page_clamp(self):
        captured = {}
        await self._call(captured=captured, page=0)
        self.assertEqual(captured["page"], 1)
        await self._call(captured=captured, page=99999)
        self.assertEqual(captured["page"], 500)

    async def test_page_size_clamp(self):
        captured = {}
        await self._call(captured=captured, page_size=0)
        self.assertEqual(captured["page_size"], 1)
        await self._call(captured=captured, page_size=9999)
        self.assertEqual(captured["page_size"], 100)

    async def test_success_returns_service_dict_verbatim(self):
        svc = {"total": 2, "page": 1, "page_size": 30,
               "items": [{"id": 1}, {"id": 2}]}
        r = await self._call(actor=None, result=svc, scope="public")
        self.assertEqual(r, svc)

    def test_mcp_no_http_handler_call_no_leakage(self):
        import api.mcp_server as mcp
        full = inspect.getsource(mcp)
        seg = None
        for node in ast.walk(ast.parse(full)):
            if (isinstance(node, ast.AsyncFunctionDef)
                    and node.name == "list_skills"):
                seg = ast.get_source_segment(full, node)
        self.assertIsNotNone(seg)
        self.assertNotIn("skills_module", seg)
        self.assertNotIn("HTTPException", seg)
        self.assertNotIn("request=None", seg)
        self.assertIn("_list_service", seg)


if __name__ == "__main__":
    unittest.main()
