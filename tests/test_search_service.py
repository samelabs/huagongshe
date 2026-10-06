"""G2.3 search vertical slice tests.

覆盖:
- Service: 三 mode 直调 run_search_query(mock db)、SearchError 语义、invalid input
- HTTP contract: exact 匿名/结构匿名 401/SearchError→HTTPException 映射
- MCP: tool/schema 不变、直调 service、不经 HTTP handler、业务错误→ToolError
- Rate policy: exact 不进 structure gate;substructure/similarity cache-miss 进 gate
- Architecture(AST): service 无 fastapi/mcp import;adapter 无 DB search SQL
"""

from __future__ import annotations

import ast
import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

os.environ.setdefault(
    "HGS_DATABASE_URL",
    "postgresql+asyncpg://governance:governance@127.0.0.1:5432/unused",
)

from api.services import search as svc  # noqa: E402


_EMPTY = ([], None, [], False, None, None, False, False)


class _FakeScalars:
    def all(self):
        return []


class _FakeResult:
    def __init__(self, rows=()):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def scalar(self):
        return 0

    def scalars(self):
        return _FakeScalars()


class _FakeDB:
    def __init__(self):
        self.rollbacked = False

    async def execute(self, *_a, **_k):
        return _FakeResult()

    async def rollback(self):
        self.rollbacked = True


class ServiceTests(unittest.TestCase):
    def test_exact_normal(self):
        db = _FakeDB()
        out = asyncio.run(svc.run_search_query(
            db, "苯甲酸", "exact", None, 1, 30, 0))
        self.assertEqual(len(out), 8)
        self.assertEqual(out[3], False)  # cas_fetch_pending

    def test_substructure_requires_canonical(self):
        with self.assertRaises(svc.SearchError) as ctx:
            asyncio.run(svc.run_search_query(
                _FakeDB(), "not-a-smiles", "substructure", None, 1, 30, 0))
        self.assertEqual(ctx.exception.kind, "invalid_structure")
        self.assertEqual(ctx.exception.detail, "无法识别该 SMILES 结构")

    def test_similarity_requires_canonical(self):
        with self.assertRaises(svc.SearchError) as ctx:
            asyncio.run(svc.run_search_query(
                _FakeDB(), "zzz", "similarity", None, 1, 30, 0))
        self.assertEqual(ctx.exception.kind, "invalid_structure")

    def test_short_name_query_rejected(self):
        with self.assertRaises(svc.SearchError) as ctx:
            asyncio.run(svc.run_search_query(
                _FakeDB(), "ab", "exact", None, 1, 30, 0))
        self.assertEqual(ctx.exception.kind, "query_too_short")
        self.assertEqual(ctx.exception.detail,
                         "名称查询至少需要 3 个字符（中文至少 2 个字）")

    def test_db_error_maps_to_search_error_503_with_rollback(self):
        class _Boom:
            async def execute(self, *_a, **_k):
                raise RuntimeError("pool exhausted")

            async def rollback(self):
                pass

        with self.assertRaises(svc.SearchError) as ctx:
            asyncio.run(svc.run_search_query(
                _Boom(), "benzoic acid", "exact", None, 1, 30, 0))
        self.assertEqual(ctx.exception.kind, "backend_unavailable")
        self.assertEqual(ctx.exception.detail,
                         "查询超时，请使用更精确的名称、标识符或结构")


class HttpContractTests(unittest.TestCase):
    """HTTP adapter: 墙/错误映射/G1 selector 语义。"""

    def _search(self, actor, mode, **kw):
        from api import routes as routes_module
        db = _FakeDB()
        async def go():
            return await routes_module.search(
                actor=actor, q=kw.get("q", "benzoic acid"), mode=mode,
                threshold=kw.get("threshold", 0.7), page=1, page_size=30, db=db)
        return asyncio.run(go())

    def test_structure_anonymous_denied_401(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            self._search(None, "substructure")
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertEqual(ctx.exception.detail,
                         "结构检索（子结构/相似度）需要登录或提供 API Token")

    def test_search_error_maps_to_http_exception(self):
        from fastapi import HTTPException
        from api import routes as routes_module
        with patch.object(routes_module, "execute_search",
                          side_effect=svc.SearchError(svc.INVALID_STRUCTURE, "无法识别该 SMILES 结构")):
            with self.assertRaises(HTTPException) as ctx:
                self._search(None, "exact")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail, "无法识别该 SMILES 结构")


class McpSearchContractTests(unittest.TestCase):
    def _tool_fn(self):
        import api.mcp_server as m
        server = m.build_mcp_server()
        for call in server._tool_manager._tools.values():
            if call.name == "search_chemistry_data":
                return call.fn
        self.fail("tool 未注册")

    def test_tool_name_and_schema_unchanged(self):
        import api.mcp_server as m
        tools = asyncio.run(m.build_mcp_server().list_tools())
        tool = next(t for t in tools if t.name == "search_chemistry_data")
        schema = getattr(tool, "input_schema", None) or tool.inputSchema
        props = schema["properties"]
        self.assertEqual(set(props),
                         {"q", "mode", "threshold", "page", "page_size"})

    def test_mcp_validation_errors_toolerror(self):
        from mcp.server.mcpserver.exceptions import ToolError
        fn = self._tool_fn()
        with self.assertRaises(ToolError) as ctx:
            asyncio.run(fn(q="", mode="exact"))
        self.assertIn("q is required", str(ctx.exception))
        with self.assertRaises(ToolError) as ctx:
            asyncio.run(fn(q="CCO", mode="bogus"))
        self.assertIn("mode must be one of", str(ctx.exception))

    def test_mcp_structure_anonymous_returns_oauth_challenge(self):
        import api.mcp_server as m
        fn = self._tool_fn()

        async def anon(headers):
            return None

        with patch.object(m, "_actor_from_headers", anon):
            result = asyncio.run(fn(q="CCO", mode="substructure"))

        self.assertTrue(result.is_error)
        challenge = (result.meta or {}).get("mcp/www_authenticate") or []
        self.assertTrue(challenge)
        self.assertIn('scope="read"', challenge[0])
        self.assertIn('error="invalid_token"', challenge[0])

    def test_mcp_service_error_maps_to_toolerror(self):
        from mcp.server.mcpserver.exceptions import ToolError
        import api.mcp_server as m
        fn = self._tool_fn()
        async def anon(headers):
            return None
        with patch.object(m, "_actor_from_headers", anon), \
                patch.object(svc, "execute_search",
                             side_effect=svc.SearchError(svc.BACKEND_UNAVAILABLE, "查询超时，请使用更精确的名称、标识符或结构")):
            with self.assertRaises(ToolError) as ctx:
                asyncio.run(fn(q="CCO", mode="exact"))
        self.assertEqual(str(ctx.exception),
                         "Search timed out. Use a more specific name, identifier, or structure.")

    def test_mcp_gate_httpexception_maps_to_toolerror(self):
        from fastapi import HTTPException
        from mcp.server.mcpserver.exceptions import ToolError
        import api.mcp_server as m
        fn = self._tool_fn()

        class _Ctx:
            headers = {}

        async def actor7(headers):
            from api.core.security import Actor
            return Actor(id=7, username="a", display_name="A", email="a@t",
                         role="user", avatar_path=None, auth_kind="agent")

        async def gate_429(actor_id, bucket="structure-search"):
            from api.core.rate_limit import ResourceBusy
            raise ResourceBusy("结构检索并发已达上限，请稍后重试", retry_after=5)

        with patch.object(m, "_actor_from_headers", actor7), \
                patch("api.core.rate_limit.structure_enter", gate_429):
            with self.assertRaises(ToolError) as ctx:
                asyncio.run(fn(q="CCO", mode="substructure", ctx=_Ctx()))
        self.assertEqual(str(ctx.exception), "Structure-search concurrency limit reached. Try again shortly.")


class RatePolicyTests(unittest.TestCase):
    """exact 不误套 structure gate;结构 mode cache-miss 才进 gate(HTTP/MCP 同)。"""

    def _run_tool(self, mode):
        import api.mcp_server as m
        fn = None
        server = m.build_mcp_server()
        for call in server._tool_manager._tools.values():
            if call.name == "search_chemistry_data":
                fn = call.fn
        calls: list[str] = []

        from api.core.security import Actor

        async def actor7(headers):
            return Actor(id=7, username="a", display_name="A", email="a@t",
                         role="user", avatar_path=None, auth_kind="agent")

        async def fake_enter(actor_id, bucket="structure-search"):
            calls.append("enter")
            return []

        async def fake_exit(held, bucket="structure-search"):
            calls.append("exit")

        async def fake_cache_get(key):
            calls.append(f"cache_get:{key.split(':')[2]}")
            return None

        async def fake_cache_set(key, data, ttl=None):
            calls.append("cache_set")

        async def fake_query(db, *a, **k):
            calls.append("query")
            return ([], None, [], False, None, None, False, False)

        class _Ctx:
            headers = {}

        with patch.object(m, "_actor_from_headers", actor7), \
                patch("api.core.rate_limit.structure_enter", fake_enter), \
                patch("api.core.rate_limit.structure_exit", fake_exit), \
                patch("api.core.cache.cache_get", fake_cache_get), \
                patch("api.core.cache.cache_set", fake_cache_set), \
                patch.object(svc, "run_search_query", fake_query):
            out = asyncio.run(fn(q="CCO", mode=mode, ctx=_Ctx()))
        return calls, out

    def test_exact_mode_skips_structure_gate_and_cache(self):
        calls, _ = self._run_tool("exact")
        self.assertNotIn("enter", calls, "exact 不得误套 structure gate")
        self.assertNotIn("cache_set", calls, "exact 不得写结构缓存")
        self.assertIn("query", calls)

    def test_substructure_mode_gated_after_cache_miss(self):
        calls, _ = self._run_tool("substructure")
        self.assertEqual(calls[0], "cache_get:substructure")
        self.assertEqual(calls[1], "enter")
        self.assertIn("query", calls)
        self.assertIn("cache_set", calls)

    def test_similarity_mode_gated_after_cache_miss(self):
        calls, _ = self._run_tool("similarity")
        self.assertEqual(calls[0], "cache_get:similarity")
        self.assertEqual(calls[1], "enter")


class ArchitectureTests(unittest.TestCase):
    BANNED_MODULES = {"fastapi", "mcp", "uvicorn", "starlette"}

    def test_service_imports_transport_neutral(self):
        tree = ast.parse((REPO / "api" / "services" / "search.py").read_text("utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods = {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods = {node.module.split(".")[0]}
            else:
                continue
            self.assertFalse(
                mods & self.BANNED_MODULES,
                f"services/search.py 不得导入 {mods & self.BANNED_MODULES}")
        ids = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                ids.add(node.id)
            elif isinstance(node, ast.Attribute):
                ids.add(node.attr)
        for banned in ("HTTPException", "ToolError", "Request", "Response",
                       "UploadFile", "Depends", "Context"):
            self.assertNotIn(banned, ids)

    def test_mcp_search_does_not_call_http_handler(self):
        import inspect
        import textwrap
        import api.mcp_server as m
        src = inspect.getsource(m)
        start = src.index('@server.tool(name="search_chemistry_data"')
        end = src.index("@server.tool", start + 10)
        block = src[start:end]
        self.assertNotIn("routes_module.search(", block)
        self.assertNotIn("Request(", block)
        fn = textwrap.dedent(block[block.index("async def"):])
        tree = ast.parse(fn)
        srcs = {n.func.attr if isinstance(n.func, ast.Attribute) else n.func.id
                for n in ast.walk(tree) if isinstance(n, ast.Call)}
        self.assertIn("_execute_search", srcs,
                      "MCP search 必须直调 shared orchestration(局部 alias)")

    def test_http_and_mcp_share_search_service(self):
        mol = (REPO / "api" / "routes.py").read_text("utf-8")
        mcp = (REPO / "api" / "mcp_server.py").read_text("utf-8")
        self.assertIn("from .services.search import", mol)
        self.assertIn("execute_search", mcp)

    def test_adapters_have_no_db_search_sql(self):
        """三 mode 的 DB 查询唯一 owner=service; adapter 不复制 SQL。"""
        for path in ("api/routes.py", "api/mcp_server.py"):
            src = (REPO / path).read_text("utf-8")
            self.assertNotIn("morgan_bfp", src,
                             f"{path} 不得复制 similarity SQL")
            self.assertNotIn("substructure_snapshot(", src.split("async def search")[-1]
                             if "async def search" in src else src,
                             f"{path} 不得复制 substructure 查询")


if __name__ == "__main__":
    unittest.main()
