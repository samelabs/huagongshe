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
CPP_REAL = os.path.join(os.path.dirname(__file__), "fixtures", "cpp_cn.html")
CPP_L10N = {
    "en": "cpp_en.html", "de": "cpp_de.html", "ja": "cpp_ja.html", "ko": "cpp_ko.html",
}
CPP_L10N = {k: os.path.join(os.path.dirname(__file__), "fixtures", v) for k, v in CPP_L10N.items()}


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


class CppL10nTests(unittest.TestCase):
    """语言页真页回归(en/de/ja/ko, 2026-09-05 实拉 fixtures)。

    教训: 此前用自构模板验证语言页"通过"是幻觉——语言页与 CN 页是
    两套 DOM(en 物性在 table2, de/ja/ko 物性混在头区 dl, 安全区是
    info_list 表)。真页 fixtures 是唯一依据。
    """

    @classmethod
    def setUpClass(cls) -> None:
        missing = [v for v in CPP_L10N.values() if not os.path.exists(v)]
        if missing:
            raise unittest.SkipTest(f"语言页 fixtures 不在本机: {missing}")
        cls.entries = {
            loc: parse_cpp_page(open(p, encoding="utf-8", errors="replace").read(), locale=loc)
            for loc, p in CPP_L10N.items()
        }

    def test_identity_cross_language(self) -> None:
        for loc, e in self.entries.items():
            self.assertEqual(e["identity"]["en"], "Butyric Acid", loc)
            self.assertEqual(e["identity"]["formula"], "C4H8O2", loc)
            self.assertIn("mol_href", e["identity"], loc)
        # 本地名: de=Buttersure, ja=酪酸, ko=부탄 산(en 页无 cn 键, 合法)
        self.assertEqual(self.entries["de"]["identity"]["cn"], "Buttersure")
        self.assertEqual(self.entries["ja"]["identity"]["cn"], "酪酸")
        self.assertEqual(self.entries["ko"]["identity"]["cn"], "부탄 산")

    def test_props_physical_values(self) -> None:
        # 沸点 162°C 五语言一致(数值化), 密度 0.964
        for loc, e in self.entries.items():
            props = {p["key"]: p for p in e["props"]}
            self.assertEqual(props["bp"]["v"], 162.0, loc)
            self.assertEqual(props["bp"]["unit"], "°C", loc)
            self.assertEqual(props["density"]["v"], 0.964, loc)
            self.assertGreater(len(e["props"]), 30, loc)

    def test_safety_structured(self) -> None:
        for loc, e in self.entries.items():
            s = e["safety"]
            self.assertGreaterEqual(len(s), 10, loc)
            self.assertIn("hazard_code", s, loc)
            self.assertEqual(s["ridadr"], "UN 2820", loc)

    def test_updown_cb_numbers(self) -> None:
        for loc, e in self.entries.items():
            ud = e["updown"]
            self.assertGreaterEqual(len(ud["up"]), 5, loc)
            self.assertGreaterEqual(len(ud["down"]), 20, loc)
            up0 = ud["up"][0]
            self.assertEqual(up0["name"], "Concentrated hydrochloric acid", loc)
            self.assertEqual(up0["cb_number"], "01166822", loc)

    def test_prose_present(self) -> None:
        for loc, e in self.entries.items():
            self.assertGreaterEqual(len(e["prose"]), 5, loc)


class RedactTests(unittest.TestCase):
    def test_supplier_ref_stable(self) -> None:
        self.assertEqual(supplier_ref("10287"), supplier_ref(10287))
        self.assertNotEqual(supplier_ref("10287"), supplier_ref("10288"))


if __name__ == "__main__":
    unittest.main()
