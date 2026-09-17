"""G2.3D — Search 依赖 neutral 异常与契约恢复测试。

锁:
- chemicals 查询内核五条 Search-path 异常 = transport-neutral(无 HTTP 属性),
  detail 为 c30dfe8 基线契约原文
- services/chemicals.py 零 fastapi/starlette import(AST 级)
- run_search_query: known neutral → 语义 kind + 原 detail;
  random RuntimeError → generic BACKEND_UNAVAILABLE 兜底(不被吞)
- HTTP kind→status 映射恢复基线: 422/400/503 各自原文
- MCP SearchError → ToolError(detail) 不覆盖
"""

from __future__ import annotations

import ast
import inspect
import unittest

from api.services import chemicals as chem
from api.services import search as svc


TOO_SMALL_DETAIL = (
    f"子结构过小，请至少提供 {chem.MIN_SUBSTRUCTURE_HEAVY_ATOMS} 个非氢原子"
)
SLOW_DETAIL = "该子结构检索过慢，请稍后重试或使用更精确的结构"
TIMEOUT_DETAIL = "查询超时，请使用更精确的结构"
GENERIC_TIMEOUT = "查询超时，请使用更精确的名称、标识符或结构"


class NeutralHelperExceptionTests(unittest.TestCase):
    """§10: 五个 neutral exception 类型/detail/无 HTTP 属性。"""

    def test_invalid_smiles_raises_neutral_with_exact_detail(self) -> None:
        with self.assertRaises(chem.InvalidSmilesError) as ctx:
            chem.bounded_substructure_smiles("not-a-smiles!")
        self.assertEqual(str(ctx.exception), "无法识别该 SMILES 结构")

    def test_too_small_raises_neutral_with_exact_detail(self) -> None:
        # 乙醇: 合法结构但重原子 < MIN
        with self.assertRaises(chem.SubstructureTooSmallError) as ctx:
            chem.bounded_substructure_smiles("CCO")
        self.assertEqual(str(ctx.exception), TOO_SMALL_DETAIL)

    def test_invalid_doi_raises_neutral_with_exact_detail(self) -> None:
        class _FakeDB:
            async def execute(self, *_a, **_kw):
                class _R:
                    def fetchall(self_inner):
                        return []
                return _R()

        # doi: 前缀 + normalize 失败 → InvalidDoiError
        with self.assertRaises(chem.InvalidDoiError) as ctx:
            import asyncio
            asyncio.run(chem.reaction_lookup(_FakeDB(), "doi:!!!", 10))
        self.assertEqual(str(ctx.exception), "DOI 格式不正确")

    def test_neutral_exceptions_carry_no_http_attributes(self) -> None:
        for exc_cls in (chem.InvalidSmilesError, chem.SubstructureTooSmallError,
                        chem.InvalidDoiError, chem.SubstructureUnavailableError):
            for attr in ("status", "status_code", "headers"):
                self.assertNotIn(attr, dir(exc_cls("x")))

    def test_substructure_unavailable_is_plain_exception(self) -> None:
        self.assertTrue(issubclass(chem.SubstructureUnavailableError, Exception))
        self.assertNotIn("status_code", dir(chem.SubstructureUnavailableError("x")))


class ChemicalsServiceNeutralityTests(unittest.TestCase):
    """§4/§14: chemicals service 真 neutral(AST 级)。"""

    def test_no_fastapi_or_starlette_import(self) -> None:
        source = inspect.getsource(chem)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn("fastapi", alias.name)
                    self.assertNotIn("starlette", alias.name)
            elif isinstance(node, ast.ImportFrom):
                self.assertNotIn("fastapi", node.module or "")
                self.assertNotIn("starlette", node.module or "")

    def test_no_httpexception_reference(self) -> None:
        source = inspect.getsource(chem)
        self.assertNotIn("HTTPException", source)


class _FakeDB:
    def __init__(self) -> None:
        self.rollbacks = 0

    async def execute(self, *_a, **_kw):
        raise AssertionError("不应触达 DB")

    async def rollback(self) -> None:
        self.rollbacks += 1


class SearchSemanticMappingTests(unittest.IsolatedAsyncioTestCase):
    """§11: known neutral → kind/detail; generic 兜底保留。"""

    async def test_invalid_smiles_maps_invalid_structure(self) -> None:
        with self.assertRaises(svc.SearchError) as ctx:
            await svc.run_search_query(
                _FakeDB(), "CCO", "substructure", None, 1, 30, 0,
            )
        self.assertEqual(ctx.exception.kind, svc.INVALID_STRUCTURE)
        self.assertEqual(ctx.exception.detail, "无法识别该 SMILES 结构")

    async def test_random_runtime_error_maps_generic_backend_unavailable(self) -> None:
        class _BoomDB(_FakeDB):
            async def execute(self, *_a, **_kw):
                raise RuntimeError("boom")

        with self.assertRaises(svc.SearchError) as ctx:
            # exact 模式第一步就 SET LOCAL statement_timeout → RuntimeError
            await svc.run_search_query(_BoomDB(), "benzoic acid", "exact", None, 1, 30, 0)
        self.assertEqual(ctx.exception.kind, svc.BACKEND_UNAVAILABLE)
        self.assertEqual(ctx.exception.detail, GENERIC_TIMEOUT)

    def test_handler_order_specific_before_generic(self) -> None:
        """§11 附加: except 顺序 — neutral handlers 必须在 except Exception 之前。"""
        source = inspect.getsource(svc.run_search_query)
        idx_neutral = source.index("except InvalidSmilesError")
        idx_generic = source.index("except Exception as exc")
        self.assertLess(idx_neutral, idx_generic)
        self.assertNotIn("except HTTPException", source)




class _NoDB:
    """run_search_query 不应触达 DB 的测试替身(触达即失败)。"""

    async def execute(self, *_a, **_kw):
        raise AssertionError("不应触达 DB")

    async def rollback(self) -> None:
        pass


class _BoomQueries:
    """按调用次数依次抛指定 neutral 异常的 DB 替身(驱动 run_search_query)。"""

    def __init__(self, booms):
        self.booms = list(booms)
        self.rollbacks = 0

    async def execute(self, *_a, **_kw):
        if self.booms:
            raise self.booms.pop(0)
        raise AssertionError("超出预期的 DB 调用")

    async def rollback(self) -> None:
        self.rollbacks += 1


class SearchKindMappingViaRunQueryTests(unittest.IsolatedAsyncioTestCase):
    """§11: 经 run_search_query 真实入口锁 kind+detail(不受 cache 影响)。"""

    async def test_too_small_maps_substructure_too_small(self) -> None:
        # exact 模式第一步 SET LOCAL 不会 raise; 用 canonical=None+substructure
        # 走 INVALID_STRUCTURE, 再直接驱动 bounded 校验路径:
        with self.assertRaises(svc.SearchError) as ctx:
            await svc.run_search_query(
                _NoDB(), "CCO", "substructure", "CCO", 1, 30, 0,
            )
        self.assertEqual(ctx.exception.kind, svc.SUBSTRUCTURE_TOO_SMALL)
        self.assertEqual(ctx.exception.detail, TOO_SMALL_DETAIL)

    async def test_invalid_doi_maps_invalid_doi_kind(self) -> None:
        class _Scalars:
            def all(self_inner):
                return []

        class _R:
            def fetchall(self_inner):
                return []

            def scalars(self_inner):
                return _Scalars()

        class _DoiDB:
            async def execute(self, *_a, **_kw):
                return _R()

        with self.assertRaises(svc.SearchError) as ctx:
            await svc.run_search_query(
                _DoiDB(), "doi:!!!", "exact", None, 1, 30, 0,
            )
        self.assertEqual(ctx.exception.kind, svc.INVALID_DOI)
        self.assertEqual(ctx.exception.detail, "DOI 格式不正确")


class HttpContractRecoveryTests(unittest.TestCase):
    """§12: c30dfe8 基线 HTTP status 契约恢复(kind→status 映射)。"""

    def _status_map(self):
        import api.routes as routes
        return routes._STATUS_BY_KIND

    def test_status_mapping_restores_baseline(self) -> None:
        m = self._status_map()
        self.assertEqual(m[svc.INVALID_STRUCTURE], 400)
        self.assertEqual(m[svc.SUBSTRUCTURE_TOO_SMALL], 422)
        self.assertEqual(m[svc.INVALID_DOI], 400)
        self.assertEqual(m[svc.QUERY_TOO_SHORT], 422)
        self.assertEqual(m[svc.BACKEND_UNAVAILABLE], 503)

    def test_details_are_baseline_verbatim(self) -> None:
        # detail 原文来自 chemicals 内核, 逐字对照 c30dfe8 基线
        self.assertIn("子结构过小，请至少提供", TOO_SMALL_DETAIL)
        self.assertIn("该子结构检索过慢", SLOW_DETAIL)
        self.assertEqual(TIMEOUT_DETAIL, "查询超时，请使用更精确的结构")

    def test_routes_search_maps_all_search_error_kinds(self) -> None:
        """HTTP adapter 只经 _STATUS_BY_KIND 映射 SearchError(无裸 400/422/503 搜索分支)。"""
        import api.routes as routes
        source = inspect.getsource(routes.search)
        self.assertIn("_STATUS_BY_KIND[exc.kind]", source)


class McpContractTests(unittest.TestCase):
    """§13: MCP ToolError boundary(detail 原文, 无 HTTPException 泄漏)。"""

    def test_mcp_search_maps_search_error_to_tool_error_detail(self) -> None:
        import api.mcp_server as mcp
        source = inspect.getsource(mcp)
        # search tool 的 SearchError handler 逐 detail 直传
        self.assertIn("except _SearchError as exc:", source)
        self.assertIn("raise ToolError(exc.detail) from exc", source)

    def test_mcp_search_has_no_httpexception_catch(self) -> None:
        import api.mcp_server as mcp
        from api.services import search as search_mod
        source = inspect.getsource(search_mod.run_search_query)
        # 查询内核到 MCP 边界之间不存在 except HTTPException 假 neutral
        self.assertNotIn("except HTTPException", source)


class SubstructureSnapshotNeutralTests(unittest.IsolatedAsyncioTestCase):
    """§10: slow-window / statement-timeout 两条 503 语义 path 的 neutral detail。"""

    async def test_slow_window_raises_unavailable_with_slow_detail(self) -> None:
        from unittest.mock import patch

        class _CacheHit:
            async def __call__(self, key):
                return True if key.endswith(":slow") else None

        async def fake_set(*_a, **_kw):
            return None

        with patch.object(chem, "cache_get", _CacheHit()), \
                patch.object(chem, "cache_set", fake_set):
            with self.assertRaises(chem.SubstructureUnavailableError) as ctx:
                await chem.substructure_snapshot(_FakeDB(), "C" * 40)
        self.assertEqual(str(ctx.exception), SLOW_DETAIL)

    async def test_statement_timeout_raises_unavailable_with_timeout_detail(self) -> None:
        from unittest.mock import patch

        class _QueryCanceled(Exception):
            pass

        class _Result:
            def fetchall(self_inner):
                return []

        class _TimeoutDB(_FakeDB):
            def __init__(self):
                super().__init__()
                self.calls = 0

            async def execute(self, *_a, **_kw):
                self.calls += 1
                if self.calls == 1:  # SET LOCAL statement_timeout
                    return _Result()
                raise _QueryCanceled()

        # asyncpg QueryCanceledError 判定按类型名
        _QueryCanceled.__name__ = "QueryCanceledError"
        _QueryCanceled.__qualname__ = "QueryCanceledError"

        async def fake_get(key):
            return None

        async def fake_set(*_a, **_kw):
            return None

        db = _TimeoutDB()
        with patch.object(chem, "cache_get", fake_get), \
                patch.object(chem, "cache_set", fake_set):
            with self.assertRaises(chem.SubstructureUnavailableError) as ctx:
                await chem.substructure_snapshot(db, "C" * 40)
        self.assertEqual(str(ctx.exception), TIMEOUT_DETAIL)
        self.assertEqual(db.rollbacks, 1)  # timeout 分支 rollback 已执行

    async def test_unavailable_maps_backend_unavailable_detail_preserved(self) -> None:
        """§11: SubstructureUnavailableError 经 run_search_query 保 detail。"""
        from unittest.mock import patch

        class _SnapshotBoomDB(_FakeDB):
            pass

        with patch.object(chem, "substructure_snapshot",
                          side_effect=chem.SubstructureUnavailableError(SLOW_DETAIL)), \
                patch.object(chem, "bounded_substructure_smiles", lambda smi: smi), \
                patch.object(chem, "hydrate_chemicals", return_value=[]), \
                patch.object(chem, "_snapshot_total", lambda ids, o, p: 0):
            with self.assertRaises(svc.SearchError) as ctx:
                await svc.run_search_query(
                    _SnapshotBoomDB(), "C" * 40, "substructure", "C" * 40, 1, 30, 0,
                )
        self.assertEqual(ctx.exception.kind, svc.BACKEND_UNAVAILABLE)
        self.assertEqual(ctx.exception.detail, SLOW_DETAIL)



if __name__ == "__main__":
    unittest.main()
