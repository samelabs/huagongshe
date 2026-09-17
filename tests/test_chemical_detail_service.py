"""G2.4B — Chemical Detail 共享编排与 enrichment neutral 化测试。

锁:
- get_chemical_detail: exists/not-found/enrich 语义(07e8088 起核心/完整 (core/full)
  无行为差异)/actor 上下文/priority 显式传入/job commit/status 组装/字段集合
- ChemicalNotFoundError / EnrichmentChemicalNotFoundError: neutral, 无 HTTP 属性
- services/chemicals 与 services/enrichment 零 transport import(AST 级)
- HTTP adapter: display 投影留在 adapter, 404 映射, priority policy
- MCP get_chemical: 不再调用 (call) HTTP handler, 无伪造请求 (fake Request),
  not-found → ToolError("化合物不存在"), 恒匿名(_actor_from_headers 不被调)
- /details 路由: neutral 404 → HTTP 404 原文
"""

from __future__ import annotations

import ast
import inspect
import unittest
from unittest.mock import patch

from api.services import chemicals as chem
from api.services import enrichment as enrich_svc


DETAIL_404 = "化合物不存在"


class _Scalars:
    def all(self):
        return []


class _Result:
    def fetchone(self):
        return None

    def fetchall(self):
        return []

    def scalars(self):
        return _Scalars()


class _SynonymsRow:
    """synonyms jsonb 查询: fetchone → (count, agg)。"""

    def fetchone(self):
        return (2, ["syn-1", "syn-2"])


class _FollowsRow:
    """follows 查询: fetchone → (count, exists)。"""

    def fetchone(self):
        return (0, False)


class _PubchemRow:
    """fetch_details: mappings().fetchone() → None(无 pubchem 行)。"""

    def mappings(self):
        return self

    def fetchone(self):
        return None


class _ChemicalRow:
    def __init__(self):
        self.committed = 0

    def mappings(self):
        return self

    def fetchone(self):
        return None  # fetch_details: 无 pubchem 行


class _FakeDetailDB:
    """exists 路径: fetch_chemicals 返回 1 行 dict; 其余查询通用替身。"""

    def __init__(self):
        self.commits = 0

    async def execute(self, sql, params=None):
        sql_s = str(sql)
        if "FROM chemistry.chemicals c WHERE c.id=:id" in sql_s and "count" not in sql_s:
            row = (1, None, "CCO", None, "ethanol", None, "C2H6O",
                   46.07, 46.04, "LFQSCWFLJHTTHZ-UHFFFAOYSA-N", None,
                   ["64-17-5"], [], [], [], [], [], [])
            return _RowsResult([row])
        if "jsonb_array_length" in sql_s:
            return _SynonymsRow()
        if "count(DISTINCT rc.reaction_id)" in sql_s:
            return _ScalarResult(0)
        if "community.chemical_follows" in sql_s:
            return _SynonymsRow.__class__("x") if False else _FollowsRow()
        if "SELECT pubchem_cid" in sql_s:
            return _ScalarResult(None)  # 无 cid → current, 不入队
        if "FROM chemistry.chemical_pubchem" in sql_s:
            return _PubchemRow()
        return _ScalarResult(0)

    async def commit(self):
        self.commits += 1


class _RowsResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _ScalarResult:
    def __init__(self, value):
        self._v = value

    def scalar(self):
        return self._v

    def fetchone(self):
        return (self._v,)

    def fetchall(self):
        return []

    def mappings(self):
        return self

    def scalars(self):
        return _Scalars()


DETAIL_BASE_FIELDS = {"id", "details", "enrichment", "synonym_count", "synonyms",
                      "reaction_count", "follower_count", "is_following"}


class SharedDetailOrchestrationTests(unittest.IsolatedAsyncioTestCase):
    """§17: shared orchestration 行为。"""

    async def test_chemical_not_found_raises_neutral(self):
        class _EmptyDB(_FakeDetailDB):
            async def execute(self, sql, params=None):
                return _RowsResult([])

        with self.assertRaises(chem.ChemicalNotFoundError) as ctx:
            await chem.get_chemical_detail(_EmptyDB(), 999, actor_id=None, priority=50)
        self.assertEqual(str(ctx.exception), DETAIL_404)

    async def test_exists_returns_canonical_detail(self):
        result = await chem.get_chemical_detail(
            _FakeDetailDB(), 1, actor_id=None, priority=50)
        self.assertTrue(DETAIL_BASE_FIELDS.issubset(result.keys()))
        self.assertEqual(result["enrichment"]["status"], "current")
        self.assertIsNone(result["enrichment"]["job_id"])

    async def test_priority_passed_to_enrichment(self):
        seen = {}

        async def fake_enqueue(db, cid, *, priority, allow_refresh, actor=None):
            seen["priority"] = priority
            seen["allow_refresh"] = allow_refresh
            return {"x": 1}, None, False

        with patch.object(enrich_svc, "enqueue_chemical_if_needed", fake_enqueue):
            await chem.get_chemical_detail(_FakeDetailDB(), 1, actor_id=None, priority=50)
        self.assertEqual(seen["priority"], 50)
        self.assertTrue(seen["allow_refresh"])

    async def test_queued_job_commits_and_status(self):
        async def fake_enqueue(db, cid, *, priority, allow_refresh, actor=None):
            return None, 777, True

        db = _FakeDetailDB()
        with patch.object(enrich_svc, "enqueue_chemical_if_needed", fake_enqueue):
            result = await chem.get_chemical_detail(db, 1, actor_id=None, priority=80)
        self.assertEqual(db.commits, 1)
        self.assertEqual(result["enrichment"]["status"], "queued")
        self.assertEqual(result["enrichment"]["job_id"], 777)

    async def test_stale_no_job_no_commit(self):
        async def fake_enqueue(db, cid, *, priority, allow_refresh, actor=None):
            return {"y": 2}, None, True

        db = _FakeDetailDB()
        with patch.object(enrich_svc, "enqueue_chemical_if_needed", fake_enqueue):
            result = await chem.get_chemical_detail(db, 1, actor_id=None, priority=50)
        self.assertEqual(db.commits, 0)
        self.assertEqual(result["enrichment"]["status"], "stale")

    async def test_actor_id_used_for_follow_context(self):
        """actor_id 传入 fill_detail_context(匿名=0)。"""
        seen = {}

        original = chem.fill_detail_context

        async def spy(db, result, cid, user_id):
            seen["user_id"] = user_id
            await original(db, result, cid, user_id)

        with patch.object(chem, "fill_detail_context", spy):
            await chem.get_chemical_detail(_FakeDetailDB(), 1, actor_id=42, priority=80)
        self.assertEqual(seen["user_id"], 42)

    async def test_enrich_core_full_identical_in_orchestration(self):
        """07e8088 起 enrich 选择器无行为差异(sections 机制退役) — orchestration
        不持 enrich 分支, 返回同一 canonical result。"""
        source = inspect.getsource(chem.get_chemical_detail)
        self.assertNotIn('if enrich', source)


class NeutralErrorTests(unittest.TestCase):
    def test_chemical_not_found_has_no_http_attributes(self):
        exc = chem.ChemicalNotFoundError(DETAIL_404)
        for attr in ("status", "status_code", "headers"):
            self.assertNotIn(attr, dir(exc))

    def test_enrichment_not_found_neutral(self):
        exc = enrich_svc.EnrichmentChemicalNotFoundError(DETAIL_404)
        for attr in ("status", "status_code", "headers"):
            self.assertNotIn(attr, dir(exc))


class ServiceNeutralityTests(unittest.TestCase):
    """§21: 两 service 零 transport import(AST)。"""

    def _assert_no_transport_import(self, module):
        tree = ast.parse(inspect.getsource(module))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn("fastapi", alias.name, f"{module.__name__}")
                    self.assertNotIn("starlette", alias.name)
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                self.assertNotIn("fastapi", mod)
                self.assertNotIn("starlette", mod)

    def test_chemicals_service_no_transport_import(self):
        self._assert_no_transport_import(chem)

    def test_enrichment_service_no_transport_import(self):
        self._assert_no_transport_import(enrich_svc)

    def test_enrichment_request_param_removed(self):
        sig = inspect.signature(enrich_svc.enqueue_chemical_if_needed)
        self.assertNotIn("request", sig.parameters)


class HttpAdapterTests(unittest.TestCase):
    """§18: HTTP adapter 职责。"""

    def test_routes_detail_delegates_and_maps_404(self):
        import api.routes as routes
        src = inspect.getsource(routes.chemical_detail)
        self.assertIn("get_chemical_detail", src)
        self.assertIn('raise HTTPException(404, "化合物不存在")', src)
        self.assertIn("display_details(result[\"details\"]) if display", src)
        self.assertIn("priority=80 if actor is not None else 50", src)
        self.assertNotIn("fill_detail_context(", src)
        self.assertNotIn("enqueue_chemical_if_needed", src)
        self.assertNotIn("request: Request", src)

    def test_details_route_maps_neutral_404(self):
        import api.enrichment as enr
        src = inspect.getsource(enr.chemical_details)
        self.assertIn("EnrichmentChemicalNotFoundError", src)
        self.assertIn('raise HTTPException(404, "化合物不存在")', src)
        self.assertIn("priority=80 if actor is not None else 50", src)
        self.assertNotIn("request: Request", src)


class McpAdapterTests(unittest.TestCase):
    """§19: MCP get_chemical 行为冻结。"""

    def _tool_source(self):
        import api.mcp_server as mcp
        tree = ast.parse(inspect.getsource(mcp))
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_chemical":
                return ast.get_source_segment(inspect.getsource(mcp), node)
        raise AssertionError("get_chemical not found")

    def test_no_http_handler_call_no_fake_request(self):
        src = self._tool_source()
        self.assertNotIn("routes_module", src)
        self.assertNotIn("chemical_detail(", src.replace("_get_chemical_detail", ""))
        self.assertNotIn("request=None", src)

    def test_uses_shared_orchestration_and_maps_not_found(self):
        src = self._tool_source()
        self.assertIn("_get_chemical_detail", src)
        self.assertIn("ToolError(str(exc))", src)
        self.assertIn("actor_id=None, priority=50", src)

    def test_actor_from_headers_not_called(self):
        src = self._tool_source()
        self.assertNotIn("_actor_from_headers", src)


if __name__ == "__main__":
    unittest.main()
