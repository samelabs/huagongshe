"""HGS-A2-01 回归 —— GHS 分类投影键名 ghs_classification。

事故（f1b8788 引入）：api/services/chemical_semantic.py 的投影白名单键名
被提交成占位符字面量 «redacted:ghs_…»，PB 的 GHS 危险性分类在化合物
detail 投影里静默丢失（数据库有数据、前端有展示位），REST full 与
MCP get_chemical(full) 同源受影响。

本文件锁三层：
1. 白名单元组本身含 ghs_classification，且不含任何 «redacted» 占位符
   （事故的准确形态 —— 键名字面量被替换）；
2. build_semantic_detail 纯函数：pb 带 ghs_classification →
   safety.pb_sections 原样透传；
3. MCP get_chemical(enrich="full") 拿到的 detail 含 GHS —— 以直调
   build_mcp_server 注册表里的 tool 函数 + patched service 验证
   （REST full 的编排断言在 test_chemical_detail_unified.py
   test_full_pb_ghs_classification_survives）。
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from api.services import chemical_semantic


class WhitelistKeyRegressionTests(unittest.TestCase):
    """第 1 层：白名单键名字面量（事故的准确形态）。"""

    def test_evidence_sections_contain_ghs_classification(self):
        self.assertIn("ghs_classification", chemical_semantic.PB_EVIDENCE_SECTIONS)

    def test_safety_keys_contain_ghs_classification(self):
        self.assertIn("ghs_classification", chemical_semantic.PB_SAFETY_KEYS)

    def test_no_redacted_placeholder_in_whitelists(self):
        for container in (chemical_semantic.PB_EVIDENCE_SECTIONS,
                          chemical_semantic.PB_SAFETY_KEYS,
                          chemical_semantic.PB_INDUSTRY_KEYS):
            for key in container:
                self.assertNotIn("«redacted", key,
                                 f"白名单键名被写成占位符: {key!r}")


class BuildSemanticDetailGhsTests(unittest.TestCase):
    """第 2 层：纯函数投影。"""

    def test_ghs_classification_lands_in_safety_pb_sections(self):
        ghs = {"codes": ["H302"], "pictograms": ["GHS07"]}
        detail = chemical_semantic.build_semantic_detail(
            pb={"ghs_classification": ghs, "fetched_at": "2026-09-01"},
            cb_entry=None, cb_suppliers=None,
            pb_state={"state": "current"}, cb_state={"state": "none"},
        )
        self.assertEqual(detail["safety"]["pb_sections"]["ghs_classification"], ghs)

    def test_ghs_absent_leaves_no_empty_section(self):
        detail = chemical_semantic.build_semantic_detail(
            pb={"xlogp": 1.5}, cb_entry=None, cb_suppliers=None,
            pb_state={"state": "current"}, cb_state={"state": "none"},
        )
        self.assertNotIn("ghs_classification", detail["safety"]["pb_sections"] or {})


class McpGetChemicalFullGhsTests(unittest.IsolatedAsyncioTestCase):
    """第 3 层：MCP get_chemical(full) 返回的 detail 含 GHS。"""

    async def _tool_fn(self):
        import api.mcp_server as mcp
        server = mcp.build_mcp_server()
        tools = getattr(getattr(server, "_tool_manager", None), "_tools", {})
        entry = tools.get("get_chemical")
        if entry is None:
            for attr in ("_tools", "tools"):
                registry = getattr(server, attr, None)
                if isinstance(registry, dict) and "get_chemical" in registry:
                    entry = registry["get_chemical"]
                    break
        if entry is None:
            raise AssertionError("get_chemical not found in server registry")
        fn = getattr(entry, "fn", None) or entry
        if not callable(fn):
            raise AssertionError(f"tool entry not callable: {type(entry)}")
        return fn

    async def test_mcp_full_returns_ghs_classification(self):
        ghs = {"codes": ["H302"], "pictograms": ["GHS07"]}
        fake_detail = {"id": 1, "details": {"safety": {"pb_sections": {"ghs_classification": ghs}}}}

        async def fake_get(db, chemical_id, *, actor_id=None, priority=50, enrich="core", **kwargs):
            captured.update(chemical_id=chemical_id, enrich=enrich)
            return fake_detail

        captured: dict = {}
        fn = await self._tool_fn()

        class _Ctx:
            headers: dict = {}

        from api.services import chemicals as chemicals_service
        with patch.object(chemicals_service, "get_chemical_detail", fake_get):
            result = await fn(chemical_id=1, enrich="full", ctx=_Ctx())
        self.assertEqual(result["details"]["safety"]["pb_sections"]
                         ["ghs_classification"], ghs,
                         "MCP full 丢失 GHS 分类（白名单键名回归？）")
        self.assertEqual(captured["enrich"], "full")


if __name__ == "__main__":
    unittest.main()
