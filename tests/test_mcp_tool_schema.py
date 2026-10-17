""" — MCP tools/list 契约测试(纯函数, 不触库不触网)。

锁定:
1. 工具数量 13、名字不变;
2. 描述无 docstring 缩进残留与首尾/行尾空白;
3. 每个参数有 description; 固定取值参数有 enum; 数值参数有
   minimum/maximum, 且与运行时校验用同一组常量(单一来源);
4. 空 prompts/resources: MCPServer v2 在构造时无条件注册 handler,
   capabilities 必然声明空能力 —— 本测试锁定该现状(无法关闭),
   待 SDK 提供开关后反转断言。
"""
from __future__ import annotations

import asyncio
import os
import unittest

os.environ.setdefault(
    "HGS_DATABASE_URL",
    "postgresql+asyncpg://mcp:mcp@127.0.0.1:5432/unused",
)

from api import mcp_server
from api.mcp_server import build_mcp_server

EXPECTED_TOOLS = {
    "search_chemistry_data", "get_chemical", "get_reaction",
    "render_molecule_svg", "render_reaction_svg", "list_skills",
    "get_skill", "calculate_stoichiometry", "list_my_reactions",
    "validate_reaction", "validate_skill", "create_skill", "create_reaction",
}


def _tools():
    return asyncio.run(build_mcp_server().list_tools())


class McpToolSchemaTests(unittest.TestCase):
    def test_tool_surface_frozen(self):
        tools = _tools()
        self.assertEqual(len(tools), 13)
        self.assertEqual({t.name for t in tools}, EXPECTED_TOOLS)

    def test_descriptions_have_no_indentation_or_whitespace(self):
        for tool in _tools():
            with self.subTest(tool=tool.name):
                self.assertEqual(tool.description, tool.description.strip())
                for line in tool.description.splitlines():
                    self.assertEqual(line, line.rstrip(),
                                     f"行尾空白: {line!r}")
                    self.assertFalse(line.startswith(" "),
                                     f"行首缩进残留: {line!r}")

    def test_every_parameter_has_description(self):
        for tool in _tools():
            props = tool.input_schema.get("properties", {})
            self.assertTrue(props, f"{tool.name} 应有参数")
            for name, prop in props.items():
                with self.subTest(tool=tool.name, param=name):
                    self.assertIn("description", prop, prop)

    def test_enums_match_runtime_values(self):
        tools = {t.name: t for t in _tools()}
        self.assertEqual(
            tools["search_chemistry_data"].input_schema["properties"]["mode"]["enum"],
            ["exact", "substructure", "similarity"])
        self.assertEqual(
            tools["get_chemical"].input_schema["properties"]["enrich"]["enum"],
            ["core", "full"])
        self.assertEqual(
            tools["list_skills"].input_schema["properties"]["scope"]["enum"],
            ["public", "mine"])
        self.assertEqual(
            tools["list_my_reactions"].input_schema["properties"]["visibility"]["enum"],
            ["all", "public", "private"])

    def test_numeric_bounds_share_constants_with_runtime(self):
        """schema 范围与运行时 clamp/校验常量同值(单一来源)。"""
        tools = {t.name: t for t in _tools()}
        props = tools["search_chemistry_data"].input_schema["properties"]
        self.assertEqual(props["q"]["maxLength"], mcp_server.QUERY_MAX_LENGTH)
        self.assertEqual(props["threshold"]["minimum"], mcp_server.THRESHOLD_MIN)
        self.assertEqual(props["threshold"]["maximum"], mcp_server.THRESHOLD_MAX)
        self.assertEqual(props["page"]["maximum"], mcp_server.SEARCH_PAGE_MAX)
        self.assertEqual(
            props["page_size"]["maximum"], mcp_server.SEARCH_PAGE_SIZE_MAX)
        chem = tools["get_chemical"].input_schema["properties"]["chemical_id"]
        self.assertEqual(chem["maximum"], mcp_server.ID_MAX)
        self.assertEqual(chem["minimum"], 1)
        mol = tools["render_molecule_svg"].input_schema["properties"]
        self.assertEqual(mol["width"]["minimum"], mcp_server.RENDER_SIZE_MIN)
        self.assertEqual(mol["width"]["maximum"], mcp_server.RENDER_SIZE_MAX)
        # Optional[str] 的约束在 anyOf 的 string 分支里
        smiles_schema = mol["smiles"]
        if "anyOf" in smiles_schema:
            smiles_schema = next(s for s in smiles_schema["anyOf"]
                                 if s.get("type") == "string")
        self.assertEqual(smiles_schema["maxLength"], mcp_server.SMILES_MAX_LENGTH)
        mine = tools["list_my_reactions"].input_schema["properties"]
        self.assertEqual(
            mine["page_size"]["maximum"], mcp_server.MY_REACTIONS_PAGE_SIZE_MAX)
        create = tools["create_reaction"].input_schema["properties"]
        self.assertEqual(
            create["idempotency_key"]["maxLength"],
            mcp_server.IDEMPOTENCY_KEY_MAX_LENGTH)

    def test_empty_prompts_resources_cannot_be_omitted(self):
        """MCPServer v2 构造时无条件注册 prompts/resources handler,
        capabilities 恒声明(即使为空)。SDK 无关闭开关 —— 锁定现状。"""
        server = build_mcp_server()
        self.assertEqual(asyncio.run(server.list_prompts()), [])
        self.assertEqual(asyncio.run(server.list_resources()), [])


if __name__ == "__main__":
    unittest.main()
