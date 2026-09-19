"""E9-B §3/§4 — Admin Pipeline 有界 SQL 与治理伪指标删除的防回归契约。

源码级锁:
- chemical_cb locale 聚合前必须有 fetched_at 时间窗口
- Pipeline 不允许 chemical_pubchem all-time count(*)
- Pipeline 不允许 chemical_supplier_listing all-time exact count
- Pipeline 不允许 seed exact runtime scan
- seed_enqueued_no_job / resolver_events 全仓消失(backend/panel/tests 文案)
- 缓存机制(LKG/SWR/single-flight)不变
"""
from __future__ import annotations

import inspect
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class BoundedSqlContractTests(unittest.TestCase):
    """_scan_critical/_scan_supplier 已删面的静态锁。"""

    def setUp(self):
        import api.admin as admin_module
        self.admin_src = inspect.getsource(admin_module)

    def test_cb_locale_aggregation_has_time_window(self):
        """chemical_cb GROUP BY locale 必须前置 fetched_at 窗口。"""
        # 找出所有 chemical_cb locale 聚合语句
        for m in re.finditer(
                r"FROM chemistry\.chemical_cb(\s|\n)*?GROUP BY locale", self.admin_src):
            statement = m.group(0)
            self.assertIn(
                "fetched_at >= current_date", statement,
                "chemical_cb locale 聚合缺时间窗口(无界全表扫回归)")

    def test_no_cb_locale_unbounded_aggregation_remains(self):
        """不允许出现无窗口的 `FROM chemistry.chemical_cb GROUP BY locale`。"""
        for m in re.finditer(
                r"count\(\*\)([^;]*?)FROM chemistry\.chemical_cb([^;]*?)GROUP BY locale",
                self.admin_src, re.S):
            between = m.group(2)
            self.assertIn("fetched_at >=", between,
                          "chemical_cb 无界 locale 聚合回归")

    def test_no_pubchem_all_time_count(self):
        """PB all-time count(*) 禁止: 每条 chemical_pubchem 聚合必须带窗口。"""
        for m in re.finditer(
                r"FROM chemistry\.chemical_pubchem([^;]*?)(?:\)\)\)|;|\"\"\")",
                self.admin_src, re.S):
            segment = m.group(0)
            if "count(*)" in segment or "count" in segment:
                self.assertIn(
                    "fetched_at >= current_date", segment,
                    f"PB 无窗口 count 回归: {segment[:120]!r}")

    def test_no_supplier_all_time_count(self):
        self.assertNotIn(
            "FROM chemistry.chemical_supplier_listing\n    \"\"\")",
            self.admin_src.replace(" ", ""))
        for m in re.finditer(
                r"count\(\*\)(?:(?!fetched_at).)*?FROM chemistry\.chemical_supplier_listing",
                self.admin_src, re.S):
            self.fail("supplier listing 无界 count 回归")

    def test_no_seed_runtime_scan(self):
        self.assertNotIn("ingestion.chemicalbook_seed", self.admin_src,
                         "seed 账本不得出现在 runtime pipeline(admin)")

    def test_no_total_rows_fields(self):
        """响应字段: rows 只有 today; locale 行无 total。"""
        self.assertNotIn('"rows": {"today": int(cb_today), "total"', self.admin_src)
        self.assertNotIn('"total": int(r[2])', self.admin_src)


class GovernanceRemovedCapabilityTests(unittest.TestCase):
    """§4: seed_enqueued_no_job / resolver_events 彻底消失。"""

    def test_backend_sections_removed(self):
        import api.services.pipeline_governance as gov
        src = inspect.getsource(gov)
        self.assertNotIn('"seed_enqueued_no_job":', src)
        self.assertNotIn("async def seed_enqueued_no_job", src)
        self.assertNotIn('"resolver_events":', src)
        self.assertNotIn("resolver_events_note", src)
        self.assertNotIn('"seed_enqueued_no_job"', src.split("# E9-B")[0])

    def test_drilldown_removed(self):
        import api.services.pipeline_governance as gov
        src = inspect.getsource(gov)
        self.assertNotIn('"seed_enqueued_no_job": "deferred', src)

    def test_frontend_removed(self):
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        with open(os.path.join(
                root, "web/components/samelabs/GovernancePanel.tsx"),
                encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn("seed_enqueued_no_job", src)
        self.assertNotIn("resolver", src.lower().replace("resolver 事件已移除", ""))
        # 保留能力仍在
        self.assertIn("merge_total", src)
        self.assertIn("redirect_total", src)
        self.assertIn("ambiguous_seeds", src)

    def test_pipeline_panel_no_removed_runtime_fields(self):
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        with open(os.path.join(
                root, "web/components/samelabs/PipelinePanel.tsx"),
                encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn("data.supplier", src)
        self.assertNotIn("data.cb.seed", src)
        self.assertNotIn("rows.total", src)
        self.assertNotIn("l.total", src)


class CacheMechanismIntactTests(unittest.TestCase):
    """§3: LKG/SWR/single-flight 机制未被破坏。"""

    def test_cache_mechanisms_present(self):
        import api.admin as admin_module
        src = inspect.getsource(admin_module)
        for marker in ("_PIPELINE_STATS_CACHE", "_PIPELINE_STATS_LOCK",
                       "stale-while-revalidate", "_pipeline_stats_spawn_refresh"):
            self.assertIn(marker, src, f"缓存机制 {marker} 缺失")


if __name__ == "__main__":
    unittest.main()
