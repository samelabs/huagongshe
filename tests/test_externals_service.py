"""G2.4C — Chemical Externals 共享编排测试(MCP/架构/状态机补充)。

锁:
- services/cb.py 零 transport import(AST 级); orchestration 用 neutral enforce
- HTTP/MCP 均经 get_chemical_externals; MCP 无 routes_module/request=None
- MCP: not-found → ToolError("化合物不存在"); RateLimitError → ToolError(detail)
- MCP 恒匿名(_actor_from_headers 不被调) → anonymous-global 桶
- 状态机补充: cached fresh 短路 / negative 响应 shape / queued commit 顺序
"""

from __future__ import annotations

import ast
import inspect
import unittest
from unittest.mock import MagicMock, patch

from api.services import cb as cb_module
from api.services.cb import get_chemical_externals


class _Row:
    def __init__(self, value):
        self._value = value

    def fetchone(self):
        return self._value


class _Db:
    def __init__(self, row=(1, "7732-18-5")):
        self._row = row
        self.commits = 0

    async def execute(self, *a, **k):
        return _Row(self._row)

    async def commit(self):
        self.commits += 1


class StateMachineSupplementTests(unittest.IsolatedAsyncioTestCase):
    """§14 补充: cached-fresh 短路与 queued commit 顺序(直调 orchestration)。"""

    async def test_cached_fresh_short_circuit_no_limiter(self):
        events = []

        async def fake_ensure(db, cid, cas_number=None):
            events.append("ensure")
            return {"state": "fresh", "entry": {"zh": "水"}, "suppliers": ["s"]}

        with patch.object(cb_module, "ensure_externals", fake_ensure), \
             patch.object(cb_module, "enforce",
                          lambda *a: events.append("enforce") or _raise_rate()):
            result = await get_chemical_externals(_Db(), 1, actor_id=None)
        self.assertEqual(result["state"], "fresh")
        self.assertEqual(result["suppliers"], ["s"])
        self.assertEqual(events, ["ensure"])

    async def test_queued_flow_commits_after_enqueue(self):
        events = []

        async def fake_ensure(db, cid, cas_number=None):
            events.append("ensure")
            return {"state": "absent"}

        async def fake_negative(db, kind, cas_number=None):
            return False

        async def fake_sync(db, chemical_id=None, cas_number=None):
            events.append("sync")
            return None  # 网络失败

        async def fake_enqueue(db, **kwargs):
            events.append(("enqueue", kwargs.get("priority"),
                           (kwargs.get("request_context") or {}).get("reason")))
            return 555

        async def noop_enforce(*a):
            events.append("enforce")

        db = _Db()
        with patch.object(cb_module, "ensure_externals", fake_ensure), \
             patch.object(cb_module, "negative_is_fresh", fake_negative), \
             patch.object(cb_module, "sync_fetch_and_store", fake_sync), \
             patch.object(cb_module, "enqueue_cas_job", fake_enqueue), \
             patch.object(cb_module, "enforce", noop_enforce):
            result = await get_chemical_externals(db, 1, actor_id=None)
        self.assertEqual(result["state"], "queued")
        self.assertNotIn("job_id", result)  # 基线 shape: job_id 内部, 不出站
        self.assertEqual(result["entry"], None)
        self.assertEqual([e if isinstance(e, str) else e[0] for e in events],
                         ["ensure", "enforce", "sync", "enqueue"])
        self.assertEqual(events[-1][1], 80, "sync_failed 入队 priority=80")
        self.assertEqual(events[-1][2], "sync_failed")
        self.assertEqual(db.commits, 1, "enqueue 后恰一次 commit")


def _raise_rate():
    from api.core.rate_limit import RateLimited
    return RateLimited("请求过于频繁，请稍后重试")


class ServiceNeutralityTests(unittest.TestCase):
    """§18: services/cb 零 transport import; orchestration 无 HTTP 语义。"""

    def test_cb_service_no_transport_import(self):
        src = inspect.getsource(cb_module)
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn("fastapi", alias.name)
                    self.assertNotIn("starlette", alias.name)
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                self.assertNotIn("fastapi", mod)
                self.assertNotIn("starlette", mod)

    def test_orchestration_uses_neutral_enforce_only(self):
        src = inspect.getsource(get_chemical_externals)
        self.assertIn("enforce(", src)
        self.assertNotIn("enforce_http", src)
        self.assertNotIn("HTTPException", src)
        self.assertNotIn("ToolError", src)
        self.assertNotIn("429", src.replace("40", ""))
        self.assertNotIn("503", src.replace("50", ""))

    def test_redis_contract_unchanged(self):
        self.assertEqual(cb_module.CACHE_KEY, "v4:cas-ext:{chemical_id}")


class McpExternalsTests(unittest.TestCase):
    """§17: MCP adapter 行为冻结。"""

    def _tool_source(self):
        import api.mcp_server as mcp
        full = inspect.getsource(mcp)
        tree = ast.parse(full)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_chemical_externals":
                return ast.get_source_segment(full, node)
        raise AssertionError("get_chemical_externals tool not found")





class RemovedExternalsToolTests(unittest.TestCase):
    """E9-B 1.1: MCP get_chemical_externals 已删除; service 层(owner)保留。"""

    def test_mcp_tool_deleted(self):
        from api.mcp_server import build_mcp_server
        import asyncio
        tools = asyncio.run(build_mcp_server().list_tools())
        names = {t.name for t in tools}
        self.assertNotIn("get_chemical_externals", names)
