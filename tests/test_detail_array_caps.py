"""I-083 — 详情嵌数组硬上限与总数字段(纯函数, 不触库)。

build_semantic_detail 的 CB/PB 详情投影: 供应商 50、cb_aliases 200、
cb_price 50、cb_updown 每向 100、CB 物性(cb_experimental)与文字组
(uses/preparation/properties/toxicity/packaging/notes)各 100(自定口径),
全部附 *_total 总数字段; 截断时数组有界、总数仍是完整口径。
"""
from __future__ import annotations

import os
import unittest

os.environ.setdefault(
    "HGS_DATABASE_URL",
    "postgresql+asyncpg://caps:caps@127.0.0.1:5432/unused",
)

from api.services import chemical_semantic as cs


def _detail(overrides: dict | None = None) -> dict:
    entry = {
        "identity": {"cn": "哨兵", "alias_cn": [f"别名{i}" for i in range(250)],
                     "alias_en": [f"Alias{i}" for i in range(250)]},
        "props": [{"label": f"p{i}", "text": "t"} for i in range(150)],
        "prose": [{"title": "用途", "text": f"x{i}"} for i in range(150)],
        "updown": {"up": [{"name": f"u{i}"} for i in range(120)],
                    "down": [{"name": f"d{i}"} for i in range(5)]},
        "price": [{"code": "X", "pack": "1kg"} for i in range(60)],
    }
    if overrides:
        entry.update(overrides)
    return cs.build_semantic_detail(
        pb={}, cb_entry=entry,
        cb_suppliers=[{"name": f"supplier{i}"} for i in range(80)],
        pb_state={"status": "none"}, cb_state={"status": "fresh"})


class DetailArrayCapsTests(unittest.TestCase):
    def test_caps_and_totals(self):
        d = _detail()
        # 工单定值
        self.assertEqual(len(d["suppliers"]["items"]), cs.SUPPLIERS_CAP)
        self.assertEqual(d["suppliers"]["suppliers_total"], 80)
        self.assertEqual(len(d["names"]["cb_aliases"]), cs.CB_ALIASES_CAP)
        self.assertEqual(d["names"]["cb_aliases_total"], 500)
        self.assertEqual(len(d["industry"]["cb_price"]), cs.CB_PRICE_CAP)
        self.assertEqual(d["industry"]["cb_price_total"], 60)
        up = d["industry"]["cb_updown"]
        self.assertEqual(len(up["up"]), cs.CB_UPDOWN_CAP)
        self.assertEqual(up["up_total"], 120)
        self.assertEqual(len(up["down"]), 5)
        self.assertEqual(up["down_total"], 5)
        # 自定口径
        self.assertEqual(len(d["properties"]["cb_experimental"]),
                         cs.CB_PROPS_CAP)
        self.assertEqual(d["properties"]["cb_experimental_total"], 150)
        self.assertEqual(len(d["industry"]["cb_uses"]), cs.CB_PROSE_GROUP_CAP)
        self.assertEqual(d["industry"]["cb_uses_total"], 150)

    def test_small_payloads_pass_through_with_exact_totals(self):
        d = cs.build_semantic_detail(
            pb={}, cb_entry={"identity": {"cn": "小载荷"},
                              "price": [{"code": "A"}]},
            cb_suppliers=[{"name": "one"}],
            pb_state={"status": "none"}, cb_state={"status": "fresh"})
        self.assertEqual(d["suppliers"]["suppliers_total"], 1)
        self.assertEqual(d["industry"]["cb_price_total"], 1)
        self.assertEqual(d["industry"]["cb_price"], [{"code": "A"}])
        self.assertEqual(d["names"]["cb_aliases_total"], 0)
        self.assertEqual(d["names"]["cb_aliases"], [])
        self.assertEqual(d["industry"]["cb_updown"]["up_total"], 0)


if __name__ == "__main__":
    unittest.main()
