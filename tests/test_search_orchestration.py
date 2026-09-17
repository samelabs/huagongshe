"""G2.3 final — shared search orchestration tests.

锁:
- exact: 无 cache、无 gate、直接 canonicalize+query、结果组装
- 结构模式 cache hit: 不进 gate/canonicalize/query
- 结构模式 cache miss: 调用顺序 cache_get→structure_enter→canonicalize
  →run_search_query→cache_set(300)→structure_exit(finally)
- query/canonicalize 失败: structure_exit 仍执行
- SearchError 无 HTTP status 属性; service 无 fastapi import
- 缓存 key 与基线逐字一致
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
from api.services.search import SearchError, execute_search  # noqa: E402

TUP = (  # run_search_query 返回 8 元组
    [{"id": 1}], 2, [], False, "CCO", None, True, False,
)


class _Recorder:
    def __init__(self):
        self.calls: list[str] = []

    async def cache_get(self, key):
        self.calls.append(f"cache_get:{key}")
        return None

    async def cache_set(self, key, data, ttl=None):
        self.calls.append(f"cache_set:{key}:{ttl}")

    async def structure_enter(self, actor_id, bucket="structure-search"):
        self.calls.append(f"structure_enter:{actor_id}")
        return ["actor:x"]

    async def structure_exit(self, held, bucket="structure-search"):
        self.calls.append(f"structure_exit:{held}")

    async def run_query(self, db, query, mode, canonical, page, page_size,
                        offset, *, actor_id=None, threshold=0.7):
        self.calls.append(f"run_search_query:{mode}:{canonical}:{offset}")
        return TUP


def _patch_layer(rec: _Recorder):
    import api.core.cache as cache_mod
    import api.core.rate_limit as rl
    import api.services.search as svc_mod
    return [
        patch.object(cache_mod, "cache_get", rec.cache_get),
        patch.object(cache_mod, "cache_set", rec.cache_set),
        patch.object(rl, "structure_enter", rec.structure_enter),
        patch.object(rl, "structure_exit", rec.structure_exit),
        patch.object(svc_mod, "run_search_query", rec.run_query),
    ]


def _canonical_ok(query):
    def fake(query_):  # 同步函数(to_thread 契约)
        return "CCO"
    return fake


class OrchestrationExactTests(unittest.TestCase):
    def test_exact_no_cache_no_gate_direct_query(self):
        rec = _Recorder()
        patches = _patch_layer(rec)
        for p in patches:
            p.start()
        try:
            with patch("api.chemistry.canonicalize_smiles", _canonical_ok("CCO")):
                data = asyncio.run(execute_search(
                    object(), "CCO", "exact", threshold=0.7, page=1,
                    page_size=30, actor_id=None))
        finally:
            for p in patches:
                p.stop()
        # exact: 无 cache、无 gate; 只 query; 无 cache write
        # (finally 会以 held=None 调 structure_exit — no-op, 与基线一致)
        self.assertEqual([c.split(":")[0] for c in rec.calls],
                         ["run_search_query", "structure_exit"])
        self.assertIn("structure_exit:None", rec.calls)
        self.assertEqual(data["chemicals"], [{"id": 1}])
        self.assertEqual(data["total"], 2)
        self.assertTrue(data["has_more"])
        self.assertFalse(data["capped"])
        self.assertEqual(data["canonical_smiles"], "CCO")

    def test_exact_page20_has_more_false(self):
        rec = _Recorder()
        patches = _patch_layer(rec)
        for p in patches:
            p.start()
        try:
            with patch("api.chemistry.canonicalize_smiles", _canonical_ok("CCO")):
                data = asyncio.run(execute_search(
                    object(), "CCO", "exact", threshold=0.7, page=20,
                    page_size=30, actor_id=None))
        finally:
            for p in patches:
                p.stop()
        self.assertFalse(data["has_more"], "page=20 契约上限 must has_more=False")


class OrchestrationStructureTests(unittest.TestCase):
    def test_cache_hit_skips_gate_canonicalize_query(self):
        rec = _Recorder()
        cached_result = {"query": "CCO", "mode": "substructure", "cached": True}
        rec.calls.clear()

        async def hit(key):
            rec.calls.append(f"cache_get:{key}")
            return cached_result

        rec.cache_get = hit  # type: ignore[method-assign]
        patches = _patch_layer(rec)
        for p in patches:
            p.start()
        try:
            out = asyncio.run(execute_search(
                object(), "CCO", "substructure", threshold=0.7, page=1,
                page_size=30, actor_id=7))
        finally:
            for p in patches:
                p.stop()
        self.assertIs(out, cached_result)
        self.assertEqual(rec.calls, ["cache_get:v2:unified-search:substructure:0.7:1:30:CCO",
                                     "structure_exit:None"])

    def test_cache_miss_full_ordering_and_key_ttl(self):
        rec = _Recorder()
        patches = _patch_layer(rec)
        for p in patches:
            p.start()
        try:
            with patch("api.chemistry.canonicalize_smiles", _canonical_ok("CCO")):
                data = asyncio.run(execute_search(
                    object(), "CCO", "similarity", threshold=0.55, page=2,
                    page_size=50, actor_id=9))
        finally:
            for p in patches:
                p.stop()
        want_key = "v2:unified-search:similarity:0.55:2:50:CCO"
        # 顺序(G2.3 final blocker 2): cache_get → structure_enter →
        # canonicalize → run_search_query → cache_set(300) → structure_exit(finally)
        self.assertEqual(rec.calls, [
            f"cache_get:{want_key}",
            "structure_enter:9",
            "run_search_query:similarity:CCO:50",
            f"cache_set:{want_key}:300",
            "structure_exit:['actor:x']",
        ])
        # key 逐字与基线一致(含 threshold round 口径)
        # key 逐字与基线一致
        self.assertTrue(all(want_key in c for c in rec.calls if "unified-search" in c))
        self.assertFalse(data is None)

    def test_query_failure_still_releases_gate(self):
        rec = _Recorder()

        async def boom(*a, **k):
            raise SearchError("invalid_structure", "无法识别该 SMILES 结构")

        rec.run_query = boom  # type: ignore[method-assign]
        patches = _patch_layer(rec)
        for p in patches:
            p.start()
        try:
            with patch("api.chemistry.canonicalize_smiles", _canonical_ok("CCO")):
                with self.assertRaises(SearchError):
                    asyncio.run(execute_search(
                        object(), "CCO", "substructure", threshold=0.7,
                        page=1, page_size=30, actor_id=7))
        finally:
            for p in patches:
                p.stop()
        self.assertIn("structure_exit:['actor:x']", rec.calls,
                      "query 失败也必须 finally 释放闸门")

    def test_canonicalize_failure_releases_gate(self):
        rec = _Recorder()

        def bad_canon(query_):  # 同步函数(to_thread 契约)
            raise ValueError("rdkit boom")

        patches = _patch_layer(rec)
        for p in patches:
            p.start()
        try:
            with patch("api.chemistry.canonicalize_smiles", bad_canon):
                with self.assertRaises(ValueError):
                    asyncio.run(execute_search(
                        object(), "CCO", "substructure", threshold=0.7,
                        page=1, page_size=30, actor_id=7))
        finally:
            for p in patches:
                p.stop()
        self.assertIn("structure_exit:['actor:x']", rec.calls)
        self.assertFalse(any(c.startswith("run_search_query") for c in rec.calls))

    def test_gate_rate_error_bubbles_neutral(self):
        from api.core.rate_limit import ResourceBusy

        async def busy(actor_id, bucket="structure-search"):
            raise ResourceBusy("结构检索并发已达上限，请稍后重试", retry_after=5)

        rec = _Recorder()
        rec.structure_enter = busy  # type: ignore[method-assign]
        patches = _patch_layer(rec)
        for p in patches:
            p.start()
        try:
            with self.assertRaises(ResourceBusy):
                asyncio.run(execute_search(
                    object(), "CCO", "substructure", threshold=0.7,
                    page=1, page_size=30, actor_id=7))
        finally:
            for p in patches:
                p.stop()
        # gate 拒绝: 未 query、未 cache write
        self.assertFalse(any(c.startswith("run_search_query") for c in rec.calls))
        self.assertFalse(any(c.startswith("cache_set") for c in rec.calls))


class SearchErrorNeutralTests(unittest.TestCase):
    def test_search_error_has_no_http_status(self):
        for kind, detail in (("invalid_structure", "无法识别该 SMILES 结构"),):
            exc = SearchError(kind, detail)
            self.assertEqual(exc.kind, kind)
            self.assertEqual(exc.detail, detail)
            self.assertFalse(hasattr(exc, "status"))
            self.assertFalse(hasattr(exc, "status_code"))
            self.assertFalse(hasattr(exc, "headers"))

    def test_cache_set_failure_propagates_and_releases_gate(self):
        """基线语义: cache_set 异常传播(不吞), gate 仍 finally 释放。"""
        rec = _Recorder()

        async def boom_set(key, data, ttl=None):
            rec.calls.append(f"cache_set:{key}:{ttl}:FAIL")
            raise ConnectionError("redis write failed")

        rec.cache_set = boom_set  # type: ignore[method-assign]
        patches = _patch_layer(rec)
        for p in patches:
            p.start()
        try:
            with patch("api.chemistry.canonicalize_smiles", _canonical_ok("CCO")):
                with self.assertRaises(ConnectionError):
                    asyncio.run(execute_search(
                        object(), "CCO", "substructure", threshold=0.7,
                        page=1, page_size=30, actor_id=7))
        finally:
            for p in patches:
                p.stop()
        self.assertIn("structure_exit:['actor:x']", rec.calls,
                      "cache_set 失败也必须 finally 释放闸门")
        self.assertEqual(rec.calls[-1], "structure_exit:['actor:x']")

    def test_service_imports_no_http_framework(self):
        tree = ast.parse((REPO / "api" / "services" / "search.py").read_text("utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots = {node.module.split(".")[0]}
            else:
                continue
            self.assertFalse(roots & {"fastapi", "starlette", "mcp", "uvicorn"},
                             f"services/search.py 不得导入 {roots}")




class ArchitectureOwnershipTests(unittest.TestCase):
    """§15: adapter → shared orchestration; adapter 不再持有编排原语。"""

    def _func_source(self, path, func_name):
        src = (REPO / path).read_text("utf-8")
        lines = src.splitlines()
        start = None
        for i, ln in enumerate(lines):
            stripped = ln.lstrip()
            if stripped.startswith(f"async def {func_name}(") or stripped.startswith(f"def {func_name}("):
                start = i
                indent = len(ln) - len(ln.lstrip())
                break
        assert start is not None, f"{func_name} not found in {path}"
        # 跳过签名(括号配平)后取到下一个列 0 非空行
        depth = 0
        body_start = start
        for i in range(start, len(lines)):
            depth += lines[i].count("(") - lines[i].count(")")
            if depth == 0 and ("):" in lines[i] or i > start and lines[i].rstrip().endswith(":")):
                body_start = i + 1
                break
        end = len(lines)
        for i in range(body_start, len(lines)):
            ln = lines[i]
            stripped = ln.lstrip()
            cur = len(ln) - len(stripped)
            if ln.strip() and cur <= indent and (
                    stripped.startswith("async def ") or stripped.startswith("def ")
                    or stripped.startswith("@") or stripped.startswith("return ")
                    and cur < indent):
                end = i
                break
        return "\n".join(lines[start:end])

    def test_http_search_delegates_to_shared_orchestration(self):
        body = self._func_source("api/routes.py", "search")
        self.assertIn("execute_search(", body)
        for banned in ("cache_get(", "cache_set(", "structure_enter",
                       "canonicalize_smiles", "run_search_query(",
                       'f"v2:unified-search', "has_more and page < 20"):
            self.assertNotIn(banned, body, f"routes.search 不应再含 {banned}")

    def test_mcp_search_delegates_to_shared_orchestration(self):
        body = self._func_source("api/mcp_server.py", "search_chemistry_data")
        self.assertIn("execute_search(", body)
        for banned in ("cache_get", "cache_set", "structure_enter",
                       "canonicalize_smiles", "run_search_query",
                       "v2:unified-search", "has_more and page < 20",
                       "routes_module"):
            self.assertNotIn(banned, body, f"MCP search 不应再含 {banned}")

    def test_orchestration_calls_query_core_and_gate(self):
        body = self._func_source("api/services/search.py", "execute_search")
        for needed in ("cache_get", "structure_enter", "canonicalize_smiles",
                       "run_search_query", "cache_set", "structure_exit"):
            self.assertIn(needed, body)



if __name__ == "__main__":
    unittest.main()
