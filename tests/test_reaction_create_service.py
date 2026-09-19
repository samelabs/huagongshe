"""G3.1C — reaction create service 测试。

锁:
- shared create orchestration 全序(rate→key 校验→幂等预检→validation→resolve
  →INSERT→race recovery→relationships→statistics→commit→notify→response)
- HTTP/MCP idempotency intentional difference(§8/§9/§10 顺序)
- 幂等命中短路;IntegrityError 竞态恢复双段
- notify after commit;created_chemicals;response shape
- neutral errors: MissingIdempotencyKey/TooLong/ReactionValidation/Rate
- 架构: service 零 transport 依赖;search 反向依赖修复;A005 create=0
"""

from __future__ import annotations

import ast
import inspect
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from api import reactions as reactions_module
from api.core import rate_limit
from api.core.rate_limit import LimiterUnavailable, RateLimited
from api.schemas.reactions import ReactionBody
from api.services import reactions as services_reactions
from api.services.reactions import (IdempotencyKeyTooLongError,
                                    MissingIdempotencyKeyError,
                                    ReactionValidationError)


def _body(**overrides):
    values = {
        "visibility": "public",
        "participants": [
            {"role": "REACTANT", "smiles": "CCO"},
            {"role": "PRODUCT", "smiles": "CC=O"},
        ],
        "source_type": "self",
    }
    values.update(overrides)
    return ReactionBody.model_validate(values)


class _Actor:
    def __init__(self, i, kind="agent"):
        self.id = i
        self.auth_kind = kind
        self.scopes = ["reaction:write"]
        self.role = "member"


class _Exec:
    """最小 db 替身: 记录语句流, 可注入 scalar 结果/异常。"""

    def __init__(self, results=None, errors=None):
        self.log = []
        self.results = results or []
        self.errors = errors or []

    async def execute(self, sql, params=None):
        sql = str(sql)
        self.log.append(sql.strip()[:60].replace("\n", " "))
        if self.errors:
            err = self.errors.pop(0)
            if err is not None:
                raise err
        for i, r in enumerate(self.results):
            key, val = r
            if key in sql and not str(val).startswith("_used"):
                self.results[i] = (key, "_used" + str(val))
                return _Result(val)
        return _Result(None)

    async def commit(self):
        self.log.append("<COMMIT>")

    async def rollback(self):
        self.log.append("<ROLLBACK>")

    def begin_nested(self):
        self.log.append("<NESTED>")
        return self


class _Result:
    def __init__(self, scalar):
        self._scalar = scalar

    def scalar(self):
        return self._scalar

    def scalar_one(self):
        return self._scalar

    def fetchone(self):
        return (1, "CCO>>CC=O", "public", 7, "agent", None, None)

    def mappings(self):
        return self

    def all(self):
        return []


class OrderingTests(unittest.TestCase):
    """§8/§10/§30: 顺序硬锁。"""

    def test_source_ordering(self):
        src = inspect.getsource(services_reactions.create_reaction)
        i_rate_m = src.index('"reaction-write-minute"')
        i_rate_d = src.index('"reaction-write-day"')
        i_missing = src.index("MissingIdempotencyKeyError()")
        i_len = src.index("IdempotencyKeyTooLongError()")
        i_precheck = src.index("SELECT id FROM chemistry.reactions")
        i_kernel = src.index("to_thread(canonical_participants")
        i_resolve = src.index("resolve_participants(")
        i_insert = src.index("INSERT INTO chemistry.reactions")
        i_rel = src.index("write_relationships(")
        i_stats = src.index("metric='reactions'")
        i_commit = src.index("await db.commit()")
        i_notify = src.index("notify_new_reaction_safely(")
        order = [i_rate_m, i_rate_d, i_missing, i_len, i_precheck, i_kernel,
                 i_resolve, i_insert, i_rel, i_stats, i_commit, i_notify]
        self.assertEqual(order, sorted(order))

    def test_notify_after_commit(self):
        src = inspect.getsource(services_reactions.create_reaction)
        self.assertLess(src.index("await db.commit()"),
                        src.index("notify_new_reaction_safely("))


class ServiceFlowTests(unittest.IsolatedAsyncioTestCase):
    """§24/§28/§29: 成功流+幂等短路+竞态恢复。"""

    async def test_success_public_create(self):
        db = _Exec(results=[("INSERT INTO chemistry.reactions", 55)])
        async def ok(*a, **k):
            return None
        with patch.object(services_reactions, "enforce", ok), \
             patch.object(services_reactions, "canonical_participants",
                          lambda b: ([{"role": "REACTANT",
                                       "canonical_smiles": "CCO",
                                       "occurrence_count": 1}], "CCO>>CC=O")), \
             patch.object(services_reactions, "resolve_participants",
                          _ap(([{**{"role": "REACTANT", "canonical_smiles": "CCO",
                                    "occurrence_count": 1}, "chemical_id": 9}], [9]))), \
             patch.object(services_reactions, "notify_new_reaction_safely",
                          _noop_recorder()), \
             patch.object(services_reactions, "reaction_response",
                          _ap({"id": 55, "created_chemical_ids": [9]})):
            result = await services_reactions.create_reaction(
                db, actor_id=7, auth_kind="agent", body=_body(),
                idempotency_key="k1")
        self.assertEqual(result["id"], 55)
        self.assertEqual(db.log.count("<COMMIT>"), 1)
        # statistics 在 commit 前
        stats_idx = next((i for i, l in enumerate(db.log)
                          if "metric='reactions'" in l), -1)
        commit_idx = db.log.index("<COMMIT>")
        self.assertLess(stats_idx, commit_idx)

    async def test_idempotency_precheck_hit_short_circuits(self):
        db = _Exec(results=[("SELECT id FROM chemistry.reactions", 88)])
        kernel = _forbid("canonical kernel")
        resolve = _forbid("resolve")
        async def ok(*a, **k):
            return None
        with patch.object(services_reactions, "enforce", ok), \
             patch.object(services_reactions, "canonical_participants", kernel), \
             patch.object(services_reactions, "resolve_participants", resolve), \
             patch.object(services_reactions, "reaction_response",
                          _ap({"id": 88})):
            result = await services_reactions.create_reaction(
                db, actor_id=7, auth_kind="agent", body=_body(),
                idempotency_key="dup")
        self.assertEqual(result["id"], 88)
        self.assertNotIn("<COMMIT>", db.log)
        self.assertNotIn("INSERT INTO chemistry.reactions", " ".join(db.log))

    async def test_agent_missing_key_after_rate(self):
        db = _Exec()
        captured = {}

        async def cap(bucket, identity, limit, window):
            captured.setdefault("buckets", []).append(bucket)

        with patch.object(services_reactions, "enforce", cap):
            with self.assertRaises(MissingIdempotencyKeyError) as ctx:
                await services_reactions.create_reaction(
                    db, actor_id=7, auth_kind="agent", body=_body(),
                    idempotency_key=None)
        self.assertEqual(ctx.exception.detail, "使用 API Token 提交必须提供 Idempotency-Key")
        # §8: rate 已消耗(两个 bucket 都 enforce 过)
        self.assertEqual(captured["buckets"],
                         ["reaction-write-minute", "reaction-write-day"])

    async def test_non_agent_missing_key_allowed(self):
        db = _Exec(results=[("INSERT INTO chemistry.reactions", 66)])
        async def ok(*a, **k):
            return None
        with patch.object(services_reactions, "enforce", ok), \
             patch.object(services_reactions, "canonical_participants",
                          lambda b: ([], "CCO>>CC=O")), \
             patch.object(services_reactions, "resolve_participants", _ap(([], []))), \
             patch.object(services_reactions, "notify_new_reaction_safely", _noop_recorder()), \
             patch.object(services_reactions, "reaction_response", _ap({"id": 66})):
            result = await services_reactions.create_reaction(
                db, actor_id=7, auth_kind="session", body=_body(),
                idempotency_key=None)
        self.assertEqual(result["id"], 66)

    async def test_key_too_long_after_rate(self):
        db = _Exec()
        buckets = []

        async def cap(bucket, *a):
            buckets.append(bucket)

        with patch.object(services_reactions, "enforce", cap):
            with self.assertRaises(IdempotencyKeyTooLongError) as ctx:
                await services_reactions.create_reaction(
                    db, actor_id=7, auth_kind="agent", body=_body(),
                    idempotency_key="x" * 201)
        self.assertEqual(ctx.exception.detail, "Idempotency-Key 不能超过 200 个字符")
        self.assertEqual(len(buckets), 2)  # rate 先消耗

    async def test_race_recovery_hit(self):
        from sqlalchemy.exc import IntegrityError
        calls = {"precheck": 0, "reread": 0}

        db = _Exec()
        orig_execute = db.execute

        state = {"phase": "precheck"}

        async def execute(sql, params=None):
            sql = str(sql)
            if "SELECT id FROM chemistry.reactions" in sql:
                phase = state["phase"]
                calls[phase] += 1
                return _Result(77 if phase == "reread" else None)
            if "INSERT INTO chemistry.reactions" in sql:
                state["phase"] = "reread"
                raise IntegrityError("s", {}, Exception("dup"))
            return await orig_execute(sql, params)

        db.execute = execute
        async def ok(*a, **k):
            return None
        with patch.object(services_reactions, "enforce", ok), \
             patch.object(services_reactions, "canonical_participants",
                          lambda b: ([], "CCO>>CC=O")), \
             patch.object(services_reactions, "resolve_participants", _ap(([], []))), \
             patch.object(services_reactions, "reaction_response",
                          _ap({"id": 77})):
            result = await services_reactions.create_reaction(
                db, actor_id=7, auth_kind="agent", body=_body(),
                idempotency_key="race")
        self.assertEqual(result["id"], 77)
        self.assertIn("<ROLLBACK>", db.log)
        self.assertEqual(calls["precheck"], 1)
        self.assertEqual(calls["reread"], 1)

    async def test_generic_integrity_error_reraised(self):
        from sqlalchemy.exc import IntegrityError
        db = _Exec()
        orig = db.execute

        async def execute(sql, params=None):
            sql = str(sql)
            if "INSERT INTO chemistry.reactions" in sql:
                raise IntegrityError("s", {}, Exception("fk"))
            return await orig(sql, params)

        db.execute = execute
        async def ok(*a, **k):
            return None
        with patch.object(services_reactions, "enforce", ok), \
             patch.object(services_reactions, "canonical_participants",
                          lambda b: ([], "CCO>>CC=O")), \
             patch.object(services_reactions, "resolve_participants", _ap(([], []))):
            with self.assertRaises(IntegrityError):
                await services_reactions.create_reaction(
                    db, actor_id=7, auth_kind="agent", body=_body(),
                    idempotency_key="k")  # 有 key 但回读 miss → re-raise
        self.assertIn("<ROLLBACK>", db.log)

    async def test_rate_limited_neutral(self):
        async def boom(*a, **k):
            raise RateLimited("请求过于频繁，请稍后重试", retry_after=60)
        db = _Exec()
        with patch.object(services_reactions, "enforce", boom):
            with self.assertRaises(RateLimited):
                await services_reactions.create_reaction(
                    db, actor_id=7, auth_kind="agent", body=_body(),
                    idempotency_key="k")
        self.assertEqual(db.log, [])  # 事务零启动

    async def test_limiter_unavailable_neutral(self):
        async def boom(*a, **k):
            raise LimiterUnavailable("限速服务暂时不可用，请稍后重试")
        with patch.object(services_reactions, "enforce", boom):
            with self.assertRaises(LimiterUnavailable):
                await services_reactions.create_reaction(
                    _Exec(), actor_id=7, auth_kind="agent", body=_body(),
                    idempotency_key="k")

    async def test_minute_policy_values(self):
        from api.core.config import settings
        captured = []

        async def cap(bucket, identity, limit, window):
            captured.append((bucket, identity, limit, window))

        with patch.object(services_reactions, "enforce", cap), \
             patch.object(services_reactions, "canonical_participants",
                          lambda b: ([], "CCO>>CC=O")), \
             patch.object(services_reactions, "resolve_participants", _ap(([], []))), \
             patch.object(services_reactions, "notify_new_reaction_safely", _noop_recorder()), \
             patch.object(services_reactions, "reaction_response", _ap({"id": 1})):
            await services_reactions.create_reaction(
                _Exec(results=[("INSERT INTO chemistry.reactions", 1)]),
                actor_id=7, auth_kind="session", body=_body(visibility="private"),
                idempotency_key=None)
        self.assertEqual(captured[0],
                         ("reaction-write-minute", "7",
                          settings.api_reaction_write_limit_per_minute, 60))
        self.assertEqual(captured[1],
                         ("reaction-write-day", "7",
                          settings.api_reaction_write_limit_per_day, 86400))


class HttpAdapterTests(unittest.TestCase):
    """§21/§26: HTTP adapter 边界。"""

    def test_adapter_no_business(self):
        src = inspect.getsource(reactions_module.create_reaction)
        for tok in ("enforce_http", "reaction-write-minute", "to_thread",
                    "resolve_participants", "INSERT INTO", "notify_"):
            self.assertNotIn(tok, src)
        self.assertIn("create_reaction_service", src)

    def test_no_request_parameter(self):
        sig = str(inspect.signature(reactions_module.create_reaction))
        self.assertNotIn("request", sig)

    def test_missing_key_maps_400(self):
        import asyncio
        async def boom(*a, **k):
            raise MissingIdempotencyKeyError()
        with patch.object(reactions_module, "create_reaction_service", boom):
            try:
                asyncio.run(reactions_module.create_reaction(
                    body=_body(), idempotency_key=None, actor=_Actor(7)))
                self.fail("expected")
            except HTTPException as exc:
                self.assertEqual((exc.status_code, exc.detail),
                                 (400, "使用 API Token 提交必须提供 Idempotency-Key"))

    def test_validation_error_maps_original(self):
        import asyncio
        async def boom(*a, **k):
            raise ReactionValidationError(
                ReactionValidationError.DUPLICATE_PARTICIPANT, "dup-detail")
        with patch.object(reactions_module, "create_reaction_service", boom):
            try:
                asyncio.run(reactions_module.create_reaction(
                    body=_body(), idempotency_key="k", actor=_Actor(7)))
                self.fail("expected")
            except HTTPException as exc:
                self.assertEqual((exc.status_code, exc.detail),
                                 (409, "dup-detail"))


class McpTests(unittest.IsolatedAsyncioTestCase):
    """§9/§27: MCP intentional difference。"""

    async def test_missing_key_service_not_called(self):
        import api.mcp_server as mcp
        from mcp.server.mcpserver.exceptions import ToolError
        server = mcp.build_mcp_server()
        tools = getattr(getattr(server, "_tool_manager", None), "_tools", {})
        fn = getattr(tools["create_reaction"], "fn", None) or tools["create_reaction"]
        calls = {"service": 0, "rate": 0}

        async def service(*a, **k):
            calls["service"] += 1
            return {}

        async def rate(*a, **k):
            calls["rate"] += 1

        with patch.object(mcp, "_actor_from_headers", _wrap(_Actor(7))), \
             patch.object(services_reactions, "create_reaction", service), \
             patch.object(services_reactions, "enforce", rate):
            with self.assertRaises(ToolError) as ctx:
                await fn(reaction=_valid(), idempotency_key="",
                         ctx=type("C", (), {"headers": {}})())
        self.assertIn("idempotency_key 必填", str(ctx.exception))
        self.assertEqual(calls, {"service": 0, "rate": 0})

    async def test_valid_key_calls_shared_service(self):
        import api.mcp_server as mcp
        server = mcp.build_mcp_server()
        tools = getattr(getattr(server, "_tool_manager", None), "_tools", {})
        fn = getattr(tools["create_reaction"], "fn", None) or tools["create_reaction"]
        captured = {}

        async def service(db, *, actor_id, auth_kind, body, idempotency_key):
            captured.update(actor_id=actor_id, auth_kind=auth_kind,
                            key=idempotency_key)
            return {"id": 5}

        class _SessionCtx:
            async def __aenter__(self):
                return "session"
            async def __aexit__(self, *a):
                return False

        with patch.object(mcp, "_actor_from_headers", _wrap(_Actor(7))), \
             patch.object(services_reactions, "create_reaction", service), \
             patch.object(mcp, "async_session", _SessionCtx):
            result = await fn(reaction=_valid(), idempotency_key="kk",
                              ctx=type("C", (), {"headers": {}})())
        self.assertEqual(result, {"id": 5})
        self.assertEqual(captured, {"actor_id": 7, "auth_kind": "agent",
                                    "key": "kk"})

    async def test_key_too_long_toolerror_before_service(self):
        import api.mcp_server as mcp
        from mcp.server.mcpserver.exceptions import ToolError
        server = mcp.build_mcp_server()
        tools = getattr(getattr(server, "_tool_manager", None), "_tools", {})
        fn = getattr(tools["create_reaction"], "fn", None) or tools["create_reaction"]
        with patch.object(mcp, "_actor_from_headers", _wrap(_Actor(7))), \
             patch.object(services_reactions, "create_reaction", _forbid("service")):
            with self.assertRaises(ToolError) as ctx:
                await fn(reaction=_valid(), idempotency_key="x" * 201,
                         ctx=type("C", (), {"headers": {}})())
        self.assertIn("不超过 200 字符", str(ctx.exception))


class ArchitectureTests(unittest.TestCase):
    """§3/§8(final state)/§32。"""

    def test_service_transport_neutral(self):
        src = inspect.getsource(services_reactions)
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                self.assertFalse(
                    node.module.startswith(("fastapi", "starlette", "mcp")))
                self.assertNotIn("reactions", node.module.split(".")[-1:][0]
                                 if node.module.startswith("..") or
                                 node.module.startswith(".") else "")
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    self.assertNotIn(alias.name, (
                        "HTTPException", "ToolError", "Request", "Response",
                        "UploadFile"))
            if isinstance(node, ast.Name):
                self.assertNotIn(node.id, (
                    "HTTPException", "ToolError", "Request", "Response"))

    def test_no_service_to_adapter_import(self):
        src = inspect.getsource(services_reactions)
        self.assertNotIn("from ..reactions import", src)
        self.assertNotIn("from .. import reactions", src)

    def test_search_reverse_dependency_fixed(self):
        src = inspect.getsource(__import__(
            "api.services.search", fromlist=["x"]))
        self.assertNotIn("from ..reactions import", src)
        # E9-B: 建行路径改为函数内局部 import, 同时引入 fail-closed 异常
        self.assertIn("from .reactions import UnresolvedIdentityError, resolve_or_create_chemical", src)

    def test_single_implementation(self):
        for helper in ("resolve_or_create_chemical", "resolve_participants",
                       "reaction_values", "write_relationships",
                       "reaction_response", "notify_new_reaction_safely",
                       "chemical_properties"):
            self.assertNotIn(f"def {helper}(",
                             inspect.getsource(reactions_module),
                             helper)
            self.assertIn(f"def {helper}(",
                          inspect.getsource(services_reactions), helper)

    def test_mcp_no_http_create_dependency(self):
        import api.mcp_server as mcp
        full = inspect.getsource(mcp)
        seg = None
        for node in ast.walk(ast.parse(full)):
            if (isinstance(node, ast.AsyncFunctionDef)
                    and node.name == "create_reaction"):
                seg = ast.get_source_segment(full, node)
        self.assertIsNotNone(seg)
        self.assertNotIn("reactions_module", seg)
        self.assertNotIn("request=None", seg)
        self.assertNotIn("_HTTPException", seg)


def _valid():
    return {
        "visibility": "public",
        "participants": [
            {"role": "REACTANT", "smiles": "CCO"},
            {"role": "PRODUCT", "smiles": "CC=O"},
        ],
        "source_type": "self",
    }


def _wrap(value):
    async def fake(headers):
        return value
    return fake


def _ap(value):
    async def fake(*a, **k):
        return value
    return fake


def _noop_recorder():
    async def fake(*a, **k):
        return None
    return fake


def _forbid(name):
    def fake(*a, **k):
        raise AssertionError(f"{name} must not be called")
    return fake


if __name__ == "__main__":
    unittest.main()
