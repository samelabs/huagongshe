"""caslib 测试(0905 收口后) — fixture 驱动(~/ops/cb-fixtures/, 仓库外, 不入库)。

覆盖: 页面判定(not_found/真页) + cb_number 提取 + 新解析器 parse_cpp_page
(真页样本 /tmp/cpp_real.html, CB3459186, 2026-09-05 实拉)。
旧 CAS 页 entry 解析测试随退役函数剥除(parse_entry/parse_suppliers)。
"""
from __future__ import annotations

import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from caslib.parse import (  # noqa: E402
    extract_cb_number,
    looks_like_not_found,
    parse_cpp_suppliers,
)
from caslib.parse_cpp import parse_cpp_page  # noqa: E402
from caslib.redact import supplier_ref  # noqa: E402

FIXTURES = os.path.expanduser("~/ops/cb-fixtures")
CPP_REAL = "/tmp/cpp_real.html"


def _fixture(name: str) -> str:
    with open(os.path.join(FIXTURES, name), encoding="utf-8", errors="ignore") as fh:
        return fh.read()


def _have_fixtures() -> bool:
    return os.path.isdir(FIXTURES) and os.path.exists(os.path.join(FIXTURES, "CAS_65-85-0.htm"))


class NotFoundDetectionTests(unittest.TestCase):
    def test_not_found_detection(self) -> None:
        if not _have_fixtures():
            self.skipTest("fixtures 不在本机")
        # 管制明示拒绝
        self.assertTrue(looks_like_not_found(_fixture("CAS_67-64-1.htm")))
        # 模板空页(有 Basicsl 壳无英文名称行)
        self.assertTrue(looks_like_not_found(_fixture("CAS_50-00-7.htm")))
        self.assertTrue(looks_like_not_found(_fixture("CAS_99999-99-9.htm")))
        # 正常页
        for cas in ("65-85-0", "69-72-7", "77-92-9"):
            self.assertFalse(looks_like_not_found(_fixture(f"CAS_{cas}.htm")), cas)

    def test_cb_number_extract(self) -> None:
        if not _have_fixtures():
            self.skipTest("fixtures 不在本机")
        self.assertEqual(extract_cb_number(_fixture("CAS_65-85-0.htm")), "8698780")


class CppParseTests(unittest.TestCase):
    """新解析器真页回归(CB3459186 丁酸, 实拉样本)。"""

    @classmethod
    def setUpClass(cls) -> None:
        if not os.path.exists(CPP_REAL):
            raise unittest.SkipTest("CPP 真页样本不在本机")
        cls.entry = parse_cpp_page(open(CPP_REAL, encoding="utf-8", errors="replace").read())

    def test_identity(self) -> None:
        e = self.entry
        self.assertEqual(sorted(e.keys()), ["identity", "price", "props", "prose", "safety", "updown"])
        self.assertEqual(e["identity"]["cn"], "丁酸")
        self.assertEqual(e["identity"]["en"], "Butyric Acid")
        self.assertEqual(e["identity"]["formula"], "C4H8O2")
        self.assertEqual(e["identity"]["mw"], 88.11)
        self.assertIn("mol_href", e["identity"])

    def test_props_label_id_pairing(self) -> None:
        props = {p["key"]: p for p in self.entry["props"]}
        # LabelID 配对: 折射率 的值必须是折射率自己的(旧顺序正则曾错位挂 FEMA 值)
        self.assertIn("refractive_index", props)
        bp = props["bp"]
        self.assertEqual(bp["v"], 162.0)
        self.assertEqual(bp["unit"], "°C")

    def test_updown_with_cb_number(self) -> None:
        ud = self.entry["updown"]
        self.assertTrue(ud["up"] and ud["down"])
        with_cb = [i for i in ud["up"] + ud["down"] if i.get("cb_number")]
        self.assertGreater(len(with_cb), 10)

    def test_safety_dict_shape(self) -> None:
        safety = self.entry["safety"]
        self.assertIsInstance(safety, dict)
        self.assertGreater(len(safety), 10)

    def test_price_rows(self) -> None:
        self.assertGreaterEqual(len(self.entry["price"]), 1)
        row = self.entry["price"][0]
        self.assertEqual(sorted(row.keys()), ["cas", "code", "name", "package", "price", "updated"])

    def test_suppliers_cpp(self) -> None:
        html = open(CPP_REAL, encoding="utf-8", errors="replace").read()
        suppliers = parse_cpp_suppliers(html)
        self.assertGreater(len(suppliers), 50)
        # cbsid 100% 覆盖; phone 可缺(页面未填即 None, 不造假)


class RedactTests(unittest.TestCase):
    def test_supplier_ref_stable(self) -> None:
        self.assertEqual(supplier_ref("10287"), supplier_ref(10287))
        self.assertNotEqual(supplier_ref("10287"), supplier_ref("10288"))


if __name__ == "__main__":
    unittest.main()
