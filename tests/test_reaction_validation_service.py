"""G3.1B — reaction validation service 测试。

锁:
- canonical kernel 错误矩阵: 3 种 neutral kind + exact detail(原 400/409 契约)
- shared service: limiter identity/bucket/limit/window, rate→neutral error
  且 kernel 不执行, 成功 shape
- HTTP: validate adapter 无 canonical 计算/rate 定义, 错误映射 400/409
- MCP: 直调 service, ToolError(detail), 无 HTTPException 依赖
- create/update kernel 适配: 位置(FOR UPDATE/owner 之后)与状态映射
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
from api.schemas.reactions import ReactionBody, ParticipantBody
from api.services import reactions as services_reactions
from api.services.reactions import (ReactionValidationError,
                                    canonical_participants)


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


class KernelTests(unittest.TestCase):
    """§13: baseline kernel contract 迁移后继续锁。"""

    def test_success_shape(self):
        participants, expr = canonical_participants(_body())
        self.assertEqual(expr, "CCO>>CC=O")
        self.assertEqual(participants[0]["canonical_smiles"], "CCO")

    def test_invalid_structure_kind_and_detail(self):
        with self.assertRaises(ReactionValidationError) as ctx:
            canonical_participants(_body(participants=[
                {"role": "REACTANT", "smiles": "not-a-smiles-$$$"},
                {"role": "PRODUCT", "smiles": "CC=O"},
            ]))
        self.assertEqual(ctx.exception.kind,
                         ReactionValidationError.INVALID_STRUCTURE)
        self.assertEqual(ctx.exception.detail,
                         "无法解析参与物结构：not-a-smiles-$$$")

    def test_duplicate_participant_kind_and_detail(self):
        with self.assertRaises(ReactionValidationError) as ctx:
            canonical_participants(_body(participants=[
                {"role": "REACTANT", "smiles": "CCO"},
                {"role": "REACTANT", "smiles": "C(C)O"},
                {"role": "PRODUCT", "smiles": "CC=O"},
            ]))
        self.assertEqual(ctx.exception.kind,
                         ReactionValidationError.DUPLICATE_PARTICIPANT)
        self.assertEqual(ctx.exception.detail,
                         "同一化合物和角色请合并为一项，并填写出现次数")

    def test_invalid_reaction_kind_and_detail(self):
        # schema 前置要求 reactant+product; 用 model_construct 绕开
        # schema validator 直击 kernel 的空模板分支(原 400 语义)。
        raw = _body()
        object.__setattr__(raw, "participants", [
            ParticipantBody(role="REACTANT", smiles="CCO"),
            ParticipantBody(role="REAGENT", smiles="O"),
        ])
        with self.assertRaises(ReactionValidationError) as ctx:
            canonical_participants(raw)
        self.assertEqual(ctx.exception.kind,
                         ReactionValidationError.INVALID_REACTION)
        self.assertEqual(ctx.exception.detail, "反应结构无法通过 RDKit 解析")

    def test_neutral_error_has_no_http_status(self):
        exc = ReactionValidationError(ReactionValidationError.INVALID_STRUCTURE, "x")
        self.assertFalse(hasattr(exc, "status_code"))
        self.assertFalse(hasattr(exc, "headers"))

    def test_single_canonical_implementation(self):
        self.assertNotIn("def canonical_participants",
                         inspect.getsource(reactions_module))
        svc = inspect.getsource(services_reactions)
        self.assertEqual(svc.count("def canonical_participants("), 1)


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    """§14: shared validate_reaction_draft。"""

    async def test_limiter_identity_and_params(self):
        captured = {}

        async def fake_enforce(bucket, identity, limit, window):
            captured.update(bucket=bucket, identity=identity,
                            limit=limit, window=window)

        with patch.object(services_reactions, "enforce", fake_enforce), \
             patch.object(services_reactions, "canonical_participants",
                          lambda b: ([], "A>>B")):
            await services_reactions.validate_reaction_draft(
                actor_id=42, body=_body())
        self.assertEqual(captured, {"bucket": "reaction-validate",
                                    "identity": "42", "limit": 20,
                                    "window": 60})

    async def test_rate_limited_neutral_and_kernel_skipped(self):
        calls = []

        def kernel_should_not_run(b):
            calls.append(1)
            return [], "A>>B"

        async def boom(*a, **k):
            raise RateLimited("请求过于频繁，请稍后重试", retry_after=30)

        with patch.object(services_reactions, "enforce", boom), \
             patch.object(services_reactions, "canonical_participants",
                          kernel_should_not_run):
            with self.assertRaises(RateLimited):
                await services_reactions.validate_reaction_draft(
                    actor_id=1, body=_body())
        self.assertEqual(calls, [])

    async def test_limiter_unavailable_neutral(self):
        async def boom(*a, **k):
            raise LimiterUnavailable("限速服务暂时不可用，请稍后重试")

        with patch.object(services_reactions, "enforce", boom):
            with self.assertRaises(LimiterUnavailable):
                await services_reactions.validate_reaction_draft(
                    actor_id=1, body=_body())

    async def test_success_dict_shape(self):
        async def ok(*a, **k):
            return None
        with patch.object(services_reactions, "enforce", ok):
            result = await services_reactions.validate_reaction_draft(
                actor_id=7, body=_body())
        self.assertEqual(sorted(result.keys()),
                         ["participants", "reaction_smiles", "valid"])
        self.assertTrue(result["valid"])
        self.assertEqual(result["reaction_smiles"], "CCO>>CC=O")
        self.assertEqual(result["participants"][0],
                         {"role": "REACTANT", "canonical_smiles": "CCO",
                          "occurrence_count": 1})

    async def test_validation_failure_neutral(self):
        async def ok(*a, **k):
            return None
        with patch.object(services_reactions, "enforce", ok):
            with self.assertRaises(ReactionValidationError):
                await services_reactions.validate_reaction_draft(
                    actor_id=7, body=_body(participants=[
                        {"role": "REACTANT", "smiles": "$$$"},
                        {"role": "PRODUCT", "smiles": "CC=O"},
                    ]))

    def test_service_transport_neutral(self):
        src = inspect.getsource(services_reactions)
        tree = ast.parse(src)
        # docstring 中的治理说明不算; AST 级零 transport 依赖/标识符
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                self.assertFalse(
                    node.module.startswith(("fastapi", "starlette", "mcp")))
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    self.assertFalse(alias.name in (
                        "HTTPException", "ToolError", "Request", "Response",
                        "UploadFile"))
            if isinstance(node, ast.Name):
                self.assertNotIn(node.id, (
                    "HTTPException", "ToolError", "Request", "Response",
                    "UploadFile"))
            if isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, (
                    "HTTPException", "ToolError"))
        # AST: 零 fastapi/starlette/mcp import, 零 ToolError 标识符
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.ImportFrom) and node.module:
                self.assertFalse(
                    node.module.startswith(("fastapi", "starlette", "mcp")))
            if isinstance(node, ast.Name) and node.id == "ToolError":
                self.fail("ToolError identifier in service")


class HttpAdapterTests(unittest.TestCase):
    """§15: HTTP validate adapter 边界。"""

    def test_adapter_has_no_canonical_or_rate(self):
        src = inspect.getsource(reactions_module.validate_reaction)
        self.assertIn("validate_reaction_draft", src)
        for tok in ("canonical_participants", "enforce_http", "20, 60",
                    "reaction-validate", "to_thread"):
            self.assertNotIn(tok, src)

    def test_kind_status_mapping(self):
        e400a = reactions_module._reaction_validation_http(
            ReactionValidationError(
                ReactionValidationError.INVALID_STRUCTURE, "d1"))
        e409 = reactions_module._reaction_validation_http(
            ReactionValidationError(
                ReactionValidationError.DUPLICATE_PARTICIPANT, "d2"))
        e400b = reactions_module._reaction_validation_http(
            ReactionValidationError(
                ReactionValidationError.INVALID_REACTION, "d3"))
        for e, code, detail in ((e400a, 400, "d1"), (e409, 409, "d2"),
                                (e400b, 400, "d3")):
            self.assertEqual(e.status_code, code)
            self.assertEqual(e.detail, detail)

    def test_rate_bridge_via_enforce_neutral(self):
        """service 冒泡 RateLimitError → handler G2.R bridge → 429。"""
        import asyncio

        async def boom(*a, **k):
            raise RateLimited("请求过于频繁，请稍后重试", retry_after=5)

        with patch.object(reactions_module, "validate_reaction_draft", boom):
            try:
                asyncio.run(reactions_module.validate_reaction(
                    body=_body(), actor=_Actor(7)))
                self.fail("expected HTTPException")
            except HTTPException as exc:
                self.assertEqual(exc.status_code, 429)
                self.assertEqual(exc.detail, "请求过于频繁，请稍后重试")
                self.assertEqual(exc.headers.get("Retry-After"), "5")


class UpdateCreateAdaptationTests(unittest.TestCase):
    """§11: create/update kernel 适配位置与映射。"""

    def test_update_validation_after_owner_check(self):
        # E3: update 全流程(行锁/owner/kernel/事务)在
        # services.reactions.update_reaction。
        src = inspect.getsource(services_reactions.update_reaction)
        i_fupdate = src.index("FOR UPDATE")
        i_owner = src.index("只能维护自己创建的反应")
        i_kernel = src.index("canonical_participants")
        self.assertLess(i_fupdate, i_owner)
        self.assertLess(i_owner, i_kernel)

    def test_update_wraps_neutral_error(self):
        # E3: kernel 消费 + neutral 错误在 service, HTTP adapter 映射。
        svc_src = inspect.getsource(services_reactions.update_reaction)
        self.assertIn("to_thread(canonical_participants", svc_src)
        http_src = inspect.getsource(reactions_module.update_reaction)
        self.assertIn("except ReactionValidationError", http_src)
        self.assertIn("update_reaction_service", http_src)

    def test_create_wraps_neutral_error(self):
        # G3.1C: create 全流程在 services.reactions.create_reaction;
        # kernel 消费+neutral 错误在 service, HTTP adapter 映射。
        svc_src = inspect.getsource(services_reactions.create_reaction)
        self.assertIn("to_thread(canonical_participants", svc_src)
        http_src = inspect.getsource(reactions_module.create_reaction)
        self.assertIn("except ReactionValidationError", http_src)
        self.assertIn("create_reaction_service", http_src)

    def test_create_mcp_no_http_dependency(self):
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

    def test_transaction_ordering_unchanged(self):
        # E3: 事务序(行锁 → kernel → UPDATE)现由 service 持有。
        src = inspect.getsource(services_reactions.update_reaction)
        # validation 仍在 FOR UPDATE 之后、UPDATE 之前
        self.assertLess(src.index("FOR UPDATE"),
                        src.index("canonical_participants"))
        self.assertLess(src.index("canonical_participants"),
                        src.index("UPDATE chemistry.reactions SET"))


class McpTests(unittest.IsolatedAsyncioTestCase):
    """§16: MCP validate_reaction。"""

    @staticmethod
    async def _tool_fn():
        import api.mcp_server as mcp
        server = mcp.build_mcp_server()
        tools = getattr(getattr(server, "_tool_manager", None), "_tools", {})
        entry = tools.get("validate_reaction")
        fn = getattr(entry, "fn", None) or entry
        return fn

    async def _call(self, reaction, actor):
        import api.mcp_server as mcp
        from mcp.server.mcpserver.exceptions import ToolError

        async def fake_actor(headers):
            return actor

        async def fake_service(*, actor_id, body):
            if reaction == "RAISE_VALIDATION":
                raise ReactionValidationError(
                    ReactionValidationError.INVALID_STRUCTURE, "无法解析参与物结构：$$$")
            if reaction == "RAISE_RATE":
                raise RateLimited("请求过于频繁，请稍后重试", retry_after=9)
            return {"valid": True, "reaction_smiles": "CCO>>CC=O",
                    "participants": []}

        with patch.object(mcp, "_actor_from_headers", fake_actor), \
             patch.object(services_reactions, "validate_reaction_draft",
                          fake_service):
            try:
                return await (await self._tool_fn())(
                    reaction=_valid_dict() if not isinstance(reaction, str)
                    or not reaction.startswith("RAISE") else
                    _invalid_dict(),
                    ctx=type("C", (), {"headers": {}})())
            except ToolError as exc:
                return exc

    async def test_no_http_handler_call_no_httpexception(self):
        import api.mcp_server as mcp
        full = inspect.getsource(mcp)
        seg = None
        for node in ast.walk(ast.parse(full)):
            if (isinstance(node, ast.AsyncFunctionDef)
                    and node.name == "validate_reaction"):
                seg = ast.get_source_segment(full, node)
        self.assertIsNotNone(seg)
        self.assertNotIn("reactions_module", seg)
        self.assertNotIn("HTTPException", seg)

    async def test_success_same_dict(self):
        r = await self._call(_valid_dict(), _Actor(7))
        self.assertEqual(r["valid"], True)
        self.assertEqual(r["reaction_smiles"], "CCO>>CC=O")

    async def test_validation_error_tool_error_detail(self):
        from mcp.server.mcpserver.exceptions import ToolError
        r = await self._call("RAISE_VALIDATION", _Actor(7))
        self.assertIsInstance(r, ToolError)
        self.assertEqual(str(r), "无法解析参与物结构：$$$")

    async def test_rate_error_tool_error_detail(self):
        from mcp.server.mcpserver.exceptions import ToolError
        r = await self._call("RAISE_RATE", _Actor(7))
        self.assertIsInstance(r, ToolError)
        self.assertEqual(str(r), "请求过于频繁，请稍后重试")

    async def test_malformed_body_prefix_unchanged(self):
        from mcp.server.mcpserver.exceptions import ToolError
        with patch.object(
                __import__("api.mcp_server", fromlist=["x"]),
                "_actor_from_headers",
                _wrap(_Actor(7))):
            try:
                await (await self._tool_fn())(
                    reaction={"visibility": "bogus"},
                    ctx=type("C", (), {"headers": {}})())
                self.fail("expected ToolError")
            except ToolError as exc:
                self.assertTrue(str(exc).startswith("草稿字段不合法: "))


class _Actor:
    def __init__(self, i):
        self.id = i
        self.scopes = ["reaction:write"]
        self.auth_kind = "agent"
        self.role = "member"
        self.auth_kind = "agent"
        self.username = "u"
        self.display_name = "U"


def _valid_dict():
    return {
        "visibility": "public",
        "participants": [
            {"role": "REACTANT", "smiles": "CCO"},
            {"role": "PRODUCT", "smiles": "CC=O"},
        ],
        "source_type": "self",
    }


def _invalid_dict():
    return _valid_dict()


def _wrap(value):
    async def fake(headers):
        return value
    return fake


def _raise(exc):
    async def boom(*a, **k):
        raise exc
    return boom


if __name__ == "__main__":
    unittest.main()
