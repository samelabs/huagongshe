"""G2.1 stoichiometry vertical slice tests.

覆盖:
- Service unit tests: 直调 services.stoichiometry.compute, 不启动 FastAPI/MCP
- HTTP contract: URL/method/auth 错误映射(400 detail 逐字)与限流编排位置
- MCP contract: tool 名/schema 不变; 结构性证明 MCP 不再调 HTTP handler、
  不构造 fake Request、service 不 import fastapi/mcp
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

from api.schemas.stoichiometry import ScaleInput  # noqa: E402
from api.services import stoichiometry as service  # noqa: E402


def _input(**over):
    base = dict(
        components=[
            {"role": "REACTANT", "smiles": "O=C(O)c1ccccc1O", "eq": 1},
            {"role": "REAGENT", "smiles": "CC(=O)OC(=O)C", "eq": 1.05},
            {"role": "PRODUCT", "smiles": "CC(=O)Oc1ccccc1C(=O)O", "eq": 1},
        ],
        basis={"index": 0, "amount_value": 10, "amount_unit": "g"},
    )
    base.update(over)
    return ScaleInput(**base)


class ServiceUnitTests(unittest.TestCase):
    """直调 service(无 FastAPI app / 无 MCP server)。"""

    def test_normal_calculation_shape(self):
        out = asyncio.run(service.compute(_input()))
        self.assertEqual(out["basis"]["index"], 0)
        self.assertEqual(out["basis"]["role"], "REACTANT")
        self.assertEqual(len(out["components"]), 3)
        self.assertIsNotNone(out["product_theoretical_yield_g"])
        self.assertIn("理论收率", out["note"])
        # 基准行恒 1.00 eq
        self.assertEqual(out["components"][0]["eq"], 1.0)
        self.assertTrue(out["components"][0]["is_basis"])
        self.assertAlmostEqual(out["basis"]["mass_g"], 10.0, places=6)
        # 组分 2(eq 1.05)的 mmol = 基准 mmol × 1.05
        self.assertAlmostEqual(
            out["components"][1]["mmol"],
            out["basis"]["mmol"] * 1.05, places=3)

    def test_mol_basis(self):
        out = asyncio.run(service.compute(_input(
            basis={"index": 0, "amount_value": 1, "amount_unit": "mol"})))
        self.assertAlmostEqual(out["basis"]["mmol"], 1000.0, places=3)

    def test_solvent_volume_by_concentration(self):
        out = asyncio.run(service.compute(_input(
            components=[
                {"role": "REACTANT", "smiles": "CCO", "eq": 1},
                {"role": "PRODUCT", "smiles": "CCOCCO", "eq": 1},
                {"role": "SOLVENT", "smiles": "CCO"},
            ],
            basis={"index": 0, "amount_value": 1, "amount_unit": "mol"},
            concentration_mol_per_l=2.0,
        )))
        # 1 mol / 2 M = 0.5 L = 500 ml
        self.assertAlmostEqual(out["solvent_volume_ml"], 500.0, places=3)
        solv = out["components"][2]
        self.assertIsNone(solv["mmol"])
        self.assertIsNone(solv["mass_g"])
        self.assertAlmostEqual(solv["volume_ml"], 500.0, places=3)

    def test_basis_index_out_of_range(self):
        with self.assertRaises(ValueError) as ctx:
            asyncio.run(service.compute(_input(
                basis={"index": 7, "amount_value": 1, "amount_unit": "g"})))
        self.assertEqual(str(ctx.exception), "基准 index 7 超出组分范围")

    def test_missing_eq_for_non_solvent(self):
        with self.assertRaises(ValueError) as ctx:
            asyncio.run(service.compute(_input(
                components=[
                    {"role": "REACTANT", "smiles": "CCO"},
                    {"role": "PRODUCT", "smiles": "CCOCCO", "eq": 1},
                ],
                basis={"index": 0, "amount_value": 1, "amount_unit": "g"})))
        self.assertEqual(str(ctx.exception), "组分 1（REACTANT）缺少 eq（仅溶剂可留空）")

    def test_multiple_solvents_with_concentration(self):
        with self.assertRaises(ValueError) as ctx:
            asyncio.run(service.compute(_input(
                components=[
                    {"role": "REACTANT", "smiles": "CCO", "eq": 1},
                    {"role": "PRODUCT", "smiles": "CCOCCO", "eq": 1},
                    {"role": "SOLVENT", "smiles": "CCO"},
                    {"role": "SOLVENT", "smiles": "c1ccccc1"},
                ],
                basis={"index": 0, "amount_value": 1, "amount_unit": "mol"},
                concentration_mol_per_l=1.0,
            )))
        self.assertEqual(str(ctx.exception), "按浓度定容仅支持单一溶剂行")

    def test_unparseable_smiles(self):
        with self.assertRaises(ValueError) as ctx:
            asyncio.run(service.compute(_input(
                components=[
                    {"role": "REACTANT", "smiles": "not-a-smiles", "eq": 1},
                    {"role": "PRODUCT", "smiles": "CCOCCO", "eq": 1},
                ],
                basis={"index": 0, "amount_value": 1, "amount_unit": "g"})))
        self.assertIn("SMILES 无法解析", str(ctx.exception))
        self.assertIn("组分 1（REACTANT）", str(ctx.exception))


class HttpContractTests(unittest.TestCase):
    """HTTP adapter: 路由契约与错误映射(不访问 DB/Redis)。"""

    def test_route_identity_unchanged(self):
        import api.stoichiometry as mod
        routes = [r for r in mod.router.routes]
        self.assertEqual(len(routes), 1)
        r = routes[0]
        self.assertEqual(r.path, "/stoichiometry/scale")
        self.assertEqual(r.methods, {"POST"})
        self.assertEqual(r.operation_id, "calculate_stoichiometry")

    def test_value_error_maps_to_400(self):
        from fastapi import HTTPException
        import api.stoichiometry as mod
        async def boom(bucket, identity, limit, window):
            return None
        with patch.object(mod, "enforce", boom):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(mod.calculate_stoichiometry(
                    body=_input(basis={"index": 9, "amount_value": 1,
                                       "amount_unit": "g"}),
                    actor=None))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail, "基准 index 9 超出组分范围")

    def test_rate_limit_orchestration_before_compute(self):
        """限流在计算之前执行(enforce 先于 service.compute)。"""
        calls: list[str] = []
        import api.stoichiometry as mod

        async def fake_enforce(bucket, identity, limit, window):
            calls.append(f"enforce:{bucket}:{identity}")

        async def fake_compute(body):
            calls.append("compute")
            return {"basis": {}, "components": [], "note": ""}

        with patch.object(mod, "enforce", fake_enforce), \
                patch.object(mod.stoich_service, "compute", fake_compute):
            out = asyncio.run(mod.calculate_stoichiometry(
                body=_input(), actor=None))
        self.assertEqual(calls, ["enforce:stoich:anon", "compute"])
        self.assertEqual(out["note"], "")


class McpContractTests(unittest.TestCase):
    """MCP: tool surface 不变 + 结构性证明不再调 HTTP handler。"""

    def _tool_source(self) -> str:
        """提取 calculate_stoichiometry tool 的函数体源码(剥掉闭包缩进),
        使其可独立 ast.parse。"""
        import inspect
        import textwrap
        import api.mcp_server as m
        src = inspect.getsource(m)
        start = src.index('@server.tool(name="calculate_stoichiometry"')
        end = src.index("@server.tool", start + 10)
        block = src[start:end]
        # 只取 "async def" 起的函数部分, 再剥闭包公共缩进
        fn = block[block.index("async def"):]
        return textwrap.dedent(fn)

    def test_tool_name_and_params_unchanged(self):
        import api.mcp_server as m
        tools = asyncio.run(m.build_mcp_server().list_tools())
        tool = next(t for t in tools if t.name == "calculate_stoichiometry")
        self.assertEqual(tool.name, "calculate_stoichiometry")
        props = tool.inputSchema["properties"] if hasattr(tool, "inputSchema") \
            else tool.inputSchema_property if hasattr(tool, "inputSchema_property") \
            else tool.input_schema["properties"]
        self.assertEqual(set(props), {"components", "basis",
                                      "concentration_mol_per_l"})

    def test_mcp_does_not_call_http_handler(self):
        """结构性: tool 函数体引用 services.stoichiometry, 不引用
        api.stoichiometry 的 HTTP handler。"""
        src = self._tool_source()
        self.assertIn("from .services import stoichiometry", src)
        # 关键: 不得 import api/stoichiometry.py(HTTP adapter 模块)
        self.assertNotIn("from . import stoichiometry", src)
        # AST 级: tool 函数体内不得出现对 HTTP handler 同名函数的调用
        tree = ast.parse(src)
        called_names = {
            node.func.attr if isinstance(node.func, ast.Attribute)
            else node.func.id
            for node in ast.walk(tree) if isinstance(node, ast.Call)
        }
        self.assertNotIn("calculate_stoichiometry", called_names,
                         "MCP tool 不得调用同名 HTTP handler 函数")

    def test_no_fake_request_construction(self):
        src = self._tool_source()
        self.assertNotIn("Request(", src)
        self.assertNotIn("request=None", src)


class McpErrorBoundaryTests(unittest.TestCase):
    """G2.1 correction: enforce/compute 的异常必须在 MCP 边界翻译。

    直接以 tool 函数对象为单位测试(mock 其内部 import 的 enforce/service),
    锁: 429/503 → ToolError(detail 原文), compute 未执行; 意外异常不被吞。
    """

    def _tool_fn(self):
        import api.mcp_server as m
        server = m.build_mcp_server()
        # FastMCP 将 tool 函数注册为 request handler; 借 list_tools 定位后
        # 从 server 内部工具表取回原函数(call_tool 直调路径)。
        fn = None
        for call in server._tool_manager._tools.values():
            if call.name == "calculate_stoichiometry":
                fn = call.fn
        if fn is None:
            self.fail("calculate_stoichiometry tool 未注册")
        return m, fn

    @staticmethod
    def _body_kwargs():
        return dict(
            components=[{"role": "REACTANT", "smiles": "O=C(O)c1ccccc1O",
                         "eq": 1},
                        {"role": "PRODUCT", "smiles": "CC(=O)Oc1ccccc1C(=O)O",
                         "eq": 1}],
            basis={"index": 0, "amount_value": 10, "amount_unit": "g"},
        )

    def test_429_becomes_tool_error_compute_not_called(self):
        from fastapi import HTTPException
        from mcp.server.mcpserver.exceptions import ToolError
        m, fn = self._tool_fn()

        async def raise_429(bucket, identity, limit, window):
            raise HTTPException(
                429, "请求过于频繁，请稍后重试",
                headers={"Retry-After": "30", "X-RateLimit-Remaining": "0"})

        computed = []

        async def fake_compute(body):
            computed.append(True)
            return {}

        import api.core.rate_limit as rl
        import api.services.stoichiometry as svc
        with patch.object(rl, "enforce", raise_429), \
                patch.object(svc, "compute", fake_compute):
            with self.assertRaises(ToolError) as ctx:
                asyncio.run(fn(**self._body_kwargs()))
        self.assertEqual(str(ctx.exception), "请求过于频繁，请稍后重试")
        self.assertEqual(computed, [])

    def test_503_becomes_tool_error_compute_not_called(self):
        from fastapi import HTTPException
        from mcp.server.mcpserver.exceptions import ToolError
        m, fn = self._tool_fn()

        async def raise_503(bucket, identity, limit, window):
            raise HTTPException(503, "限速服务暂时不可用，请稍后重试")

        computed = []

        async def fake_compute(body):
            computed.append(True)
            return {}

        import api.core.rate_limit as rl
        import api.services.stoichiometry as svc
        with patch.object(rl, "enforce", raise_503), \
                patch.object(svc, "compute", fake_compute):
            with self.assertRaises(ToolError) as ctx:
                asyncio.run(fn(**self._body_kwargs()))
        self.assertEqual(str(ctx.exception), "限速服务暂时不可用，请稍后重试")
        self.assertEqual(computed, [])

    def test_validation_value_error_still_tool_error(self):
        from mcp.server.mcpserver.exceptions import ToolError
        _, fn = self._tool_fn()

        async def ok(bucket, identity, limit, window):
            return None

        async def bad_compute(body):
            raise ValueError("基准 index 9 超出组分范围")

        import api.core.rate_limit as rl
        import api.services.stoichiometry as svc
        with patch.object(rl, "enforce", ok), \
                patch.object(svc, "compute", bad_compute):
            with self.assertRaises(ToolError) as ctx:
                asyncio.run(fn(**self._body_kwargs()))
        self.assertEqual(str(ctx.exception), "基准 index 9 超出组分范围")

    def test_unexpected_exception_not_swallowed(self):
        """意外异常(非 ValueError/HTTPException)必须原样穿透, 不得被
        except-Exception 兜底吞成 ToolError。"""
        from mcp.server.mcpserver.exceptions import ToolError
        _, fn = self._tool_fn()

        async def ok(bucket, identity, limit, window):
            return None

        async def boom(body):
            raise RuntimeError("rdkit exploded")

        import api.core.rate_limit as rl
        import api.services.stoichiometry as svc
        with patch.object(rl, "enforce", ok), \
                patch.object(svc, "compute", boom):
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(fn(**self._body_kwargs()))
        self.assertNotIsInstance(ctx.exception, ToolError)
        self.assertEqual(str(ctx.exception), "rdkit exploded")


class ServiceBoundaryTests(unittest.TestCase):
    """service 禁 import fastapi/mcp; 业务计算唯一。"""

    BANNED_MODULES = {"fastapi", "mcp", "uvicorn", "starlette"}

    def test_service_imports_are_transport_neutral(self):
        tree = ast.parse((REPO / "api" / "services" / "stoichiometry.py")
                         .read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods = {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods = {node.module.split(".")[0]}
            else:
                continue
            self.assertFalse(
                mods & self.BANNED_MODULES,
                f"services/stoichiometry.py 不得导入 {mods & self.BANNED_MODULES}")
        # 名字级检查(排除 docstring): AST 收集全部标识符
        ids = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                ids.add(node.id)
            elif isinstance(node, ast.Attribute):
                ids.add(node.attr)
        for banned_name in ("HTTPException", "ToolError", "Request", "Response",
                            "UploadFile"):
            self.assertNotIn(banned_name, ids)

    def test_calculation_has_single_owner(self):
        """RDKit 计算核心(MolWt/CalcMolFormula)只存在于 service 一份。"""
        service_src = (REPO / "api" / "services" / "stoichiometry.py").read_text("utf-8")
        adapter_src = (REPO / "api" / "stoichiometry.py").read_text("utf-8")
        mcp_src = (REPO / "api" / "mcp_server.py").read_text("utf-8")
        self.assertIn("Descriptors.MolWt", service_src)
        self.assertNotIn("Descriptors.MolWt", adapter_src)
        self.assertNotIn("Descriptors.MolWt", mcp_src)
        self.assertNotIn("CalcMolFormula", adapter_src)
        self.assertNotIn("MolFromSmiles", adapter_src)


if __name__ == "__main__":
    unittest.main()
