"""E7 §9 — 公开契约 drift guard: 只守"已经宣称的事实"。

守:
1. web/public/llms.txt 声明的 MCP 工具数量 == 真实 MCP tool surface;
2. REST 收口后对外只走 MCP: llms.txt 逐个声明的 MCP 工具名
   必须与 api/mcp_server.py 真实 tool surface 完全一致;
3. llms.txt 不得再出现 REST 端点表 / HTTP API / agent-guide 提法;
4. 解析必须真的解析到内容(空解析 = 失败, 不允许静默通过)。

不做: 全量 OpenAPI 投影 / 第二份接口 catalog / 文档生成系统。
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

LLMS = REPO / "web" / "public" / "llms.txt"

_TOOL_COUNT_RE = re.compile(r"MCP tools \((\d+) total\)")
_TOOL_LIST_RE = re.compile(r"^\d+\.\s+`([a-z_]+)`", re.MULTILINE)
_ENDPOINT_RE = re.compile(r"`(GET|POST|PUT|PATCH|DELETE) (/api/[^`?\s]*)")


class LlmsTxtDeclaredFactsTests(unittest.TestCase):
    """llms.txt 是公开宣称面: 宣称的事实必须仍成立。"""

    def setUp(self) -> None:
        self.assertTrue(LLMS.is_file(), f"llms.txt 缺失: {LLMS}")
        self.text = LLMS.read_text(encoding="utf-8")

    def test_declared_mcp_tool_count_matches_actual_surface(self):
        m = _TOOL_COUNT_RE.search(self.text)
        self.assertIsNotNone(m, "llms.txt 未声明 MCP 工具数量")
        declared = int(m.group(1))
        from tests.test_api_contract_governance import _mcp_tool_names
        actual = _mcp_tool_names()
        self.assertEqual(declared, len(actual),
                         f"llms.txt 声明 {declared} 个, 实际 {len(actual)}: {sorted(actual)}")

    def test_declared_mcp_tool_names_match_actual_surface(self):
        """对外只走 MCP —— 工具名逐个核对, 不再核对 HTTP 端点。"""
        declared = set(_TOOL_LIST_RE.findall(self.text))
        self.assertEqual(len(declared), 13,
                         f"llms.txt 工具名解析异常(应 13 个): {sorted(declared)}")
        from tests.test_api_contract_governance import _mcp_tool_names
        actual = set(_mcp_tool_names())
        self.assertEqual(
            declared, actual,
            f"llms.txt 声明与 mcp_server.py 不一致: 仅文档={sorted(declared - actual)}, "
            f"仅实现={sorted(actual - declared)}")

    def test_llms_txt_declares_no_rest_endpoints(self):
        """REST 收口: llms.txt 不出现 REST 端点表 / HTTP API / agent-guide。"""
        self.assertEqual(
            _ENDPOINT_RE.findall(self.text), [],
            "llms.txt 不得再声明 REST 端点(对外只走 MCP)")
        self.assertNotIn("HTTP API", self.text)
        self.assertNotIn("agent-guide", self.text)


if __name__ == "__main__":
    unittest.main()
