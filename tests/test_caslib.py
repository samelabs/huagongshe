"""caslib 测试 — fixture 驱动, 样本全部在库(tests/fixtures/, repo-relative)。

覆盖: 页面判定(not_found/真页) + cb_number 提取 + 新解析器 parse_cpp_page
(真页样本 tests/fixtures/cpp_cn.html = CB3459186 丁酸, 2026-09-05 实拉)。
旧 CAS 页 entry 解析测试随退役函数剥除(parse_entry/parse_suppliers)。

E7: 原先依赖仓库外路径(~/ops/cb-fixtures/)与 /tmp 预置文件 → 样本已全部
迁入 tests/fixtures/; 样本缺失不再 skip, 直接失败(路径问题不得藏成 skip)。
"""
from __future__ import annotations

import os
import re
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from caslib.parse import (  # noqa: E402
    extract_cb_number,
    looks_like_not_found,
    page_identity,
    parse_cpp_suppliers,
)
from caslib.parse_cpp import parse_cpp_page  # noqa: E402
from caslib.redact import supplier_ref  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
CPP_REAL = os.path.join(os.path.dirname(__file__), "fixtures", "cpp_cn.html")
CPP_L10N = {
    "en": "cpp_en.html", "de": "cpp_de.html", "ja": "cpp_ja.html", "ko": "cpp_ko.html",
}
CPP_L10N = {k: os.path.join(os.path.dirname(__file__), "fixtures", v) for k, v in CPP_L10N.items()}


def _fixture(name: str) -> str:
    with open(os.path.join(FIXTURES, name), encoding="utf-8", errors="ignore") as fh:
        return fh.read()


def _require_fixtures(*names: str) -> None:
    """样本必须在库: 缺失 = 测试失败(不是 skip, 也不是路径问题的另一种写法)。"""
    missing = [n for n in names if not os.path.exists(os.path.join(FIXTURES, n))]
    if missing:
        raise AssertionError(f"仓库 fixture 缺失: {missing} (期望目录 {FIXTURES})")


class NotFoundDetectionTests(unittest.TestCase):
    def test_not_found_detection(self) -> None:
        _require_fixtures(
            "CAS_67-64-1.htm", "CAS_50-00-7.htm", "CAS_99999-99-9.htm",
            "CAS_65-85-0.htm", "CAS_69-72-7.htm", "CAS_77-92-9.htm",
        )
        # 模板空页(有 Basicsl 壳无英文名称行)
        self.assertTrue(looks_like_not_found(_fixture("CAS_50-00-7.htm")))
        # 不存在的 CAS 号
        self.assertTrue(looks_like_not_found(_fixture("CAS_99999-99-9.htm")))
        # 真页必须判定为非 not_found
        for cas in ("65-85-0", "69-72-7", "77-92-9"):
            self.assertFalse(looks_like_not_found(_fixture(f"CAS_{cas}.htm")), cas)
        # 67-64-1(丙酮): 2026-09-19 实拉已是完整条目页(cb_number=3130928),
        # 不再是 0905 样本中的"管制明示拒绝"页 —— 事实更新为真页判定。
        # 该页类型当前无真实样本可采(不得自构模板), 见 E7 报告 O 段。
        self.assertFalse(looks_like_not_found(_fixture("CAS_67-64-1.htm")))
        self.assertEqual(page_identity(_fixture("CAS_67-64-1.htm")), "real")

    def test_cb_number_extract(self) -> None:
        _require_fixtures("CAS_65-85-0.htm")
        self.assertEqual(extract_cb_number(_fixture("CAS_65-85-0.htm")), "8698780")


class CppParseTests(unittest.TestCase):
    """新解析器真页回归(CB3459186 丁酸, 实拉样本)。"""

    @classmethod
    def setUpClass(cls) -> None:
        # E7: 样本在库(repo-relative), 缺失即失败 —— 不再把路径问题 skip 掉
        with open(CPP_REAL, encoding="utf-8", errors="replace") as fh:
            cls.entry = parse_cpp_page(fh.read())

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
        if missing:  # E7: 样本在库(repo-relative), 缺失即失败(不 skip)
            raise AssertionError(f"语言页 fixtures 缺失: {missing}")
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

    def test_prose_no_leading_cas_list(self) -> None:
        """0905: prose 正文首部不得有原料 CAS 罗列残留(导航残留, 非正文)。"""
        for loc, e in self.entries.items():
            for seg in e.get("prose", []):
                self.assertIsNone(
                    re.match(r"\s*\d{2,7}-\d{2}-\d[\s,，、]", seg["text"]),
                    f"{loc}: {seg['text'][:40]!r}")



class StripLeadingCasListTests(unittest.TestCase):
    """0905 prose 首部 CAS 罗列剥离: 边界矩阵(终审补)。"""

    def _f(self):
        from caslib.parse_cpp import _strip_leading_cas_list
        return _strip_leading_cas_list

    def test_design_target(self):
        f = self._f()
        self.assertEqual(f("209919-30-2 1570-64-5 一般步骤：混合"), "一般步骤：混合")
        self.assertEqual(f("107-13-1 丙烯腈"), "丙烯腈")          # 单段也剥
        self.assertEqual(f("57-50-1，蔗糖衍生物"), "蔗糖衍生物")   # 中文逗号
        self.assertEqual(f("  209919-30-2\t正文"), "正文")        # 前导空白/tab

    def test_in_text_citation_kept(self):
        f = self._f()
        # 文中引用 / 带标签前缀 / cas# 引用: 一律不剥
        self.assertEqual(f("CAS号：29049-45-4 的化合物"), "CAS号：29049-45-4 的化合物")
        self.assertEqual(f("cas# 3068-34-6 用作原料"), "cas# 3068-34-6 用作原料")
        self.assertEqual(f("一般步骤：将 1570-64-5 与水混合"), "一般步骤：将 1570-64-5 与水混合")

    def test_all_cas_no_prose_kept(self):
        f = self._f()
        # 剥完无正文残留 → 整段保留(宁可留着不吞段)
        self.assertEqual(f("209919-30-2 1570-64-5"), "209919-30-2 1570-64-5")

    def test_non_cas_numbers_kept(self):
        f = self._f()
        self.assertEqual(f("分子量 144.13 的物质"), "分子量 144.13 的物质")
        self.assertEqual(f("2024-01-15 更新"), "2024-01-15 更新")  # 双位尾段=日期形态
        self.assertEqual(f("123456789-01-2 正文"), "123456789-01-2 正文")  # >7位超限

    def test_trailing_word_after_list_kept(self):
        f = self._f()
        # 序列后第一个非CAS词就是正文, 不吞
        self.assertEqual(f("209919-30-2 1570-64-5 2000年投产装置"), "2000年投产装置")

    def test_empty_and_plain(self):
        f = self._f()
        self.assertEqual(f(""), "")
        self.assertEqual(f("无任何编号的正文"), "无任何编号的正文")

    def test_known_limit_single_digit_date(self):
        """已知边界: 形如 2024-01-1 的单尾位日期会被当作CAS段剥掉。

        概率极低(源站日期恒为两位尾段); 记录在案不修 — 加日期判断会
        把剥离逻辑与语义猜测耦合。
        """
        f = self._f()
        self.assertEqual(f("2024-01-1 版本更新"), "版本更新")


class CitationGuardTests(unittest.TestCase):
    """引文年份守卫回归: '(NTP, 1992)' 的 1992 是来源年份不是量值。

    解析单源在 caslib/parse_cpp.py(CB 链 props canonical);
    PB 派生链 exp_props/exp_limits 已废(0905 B案), 无 PB 侧守卫。
    """

    def test_guard_cb(self) -> None:
        from caslib.parse_cpp import _parse_number_from_text as parse
        self.assertEqual(parse("Insoluble (NTP, 1992)"), (None, None))
        self.assertEqual(parse("不溶 (NTP, 1992)"), (None, None))
        self.assertEqual(parse("Pyrene is a solid. (EPA, 1998)"), (None, None))
        # 真量值不受影响(含括号引文也保数值)
        v, unit = parse("140 °F (NTP, 1992)")
        self.assertEqual((v, unit), (140.0, "°F"))
        self.assertEqual(parse("162 °C"), (162.0, "°C"))
        self.assertEqual(parse("135 °C (dec)"), (135.0, "°C"))


class RedactTests(unittest.TestCase):
    def test_supplier_ref_stable(self) -> None:
        self.assertEqual(supplier_ref("10287"), supplier_ref(10287))
        self.assertNotEqual(supplier_ref("10287"), supplier_ref("10288"))


if __name__ == "__main__":
    unittest.main()
