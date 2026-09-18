"""CB mol 拉取/解析的判别与行为测试(fixtures 全部在库 tests/fixtures/, repo-relative).

样本: cb_65850.mol + CAS_65-85-0.htm (2026-08-28 实拉);
      cpp_cb2234049_{cn,en}.html (CB2234049, 2026-09-19 实拉, 见 E7 §2)。
"""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("HGS_DATABASE_URL", "postgresql+asyncpg://test:test@127.0.0.1/test")

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "cb_65850.mol")
FIXTURE_HTML = os.path.join(os.path.dirname(__file__), "fixtures", "CAS_65-85-0.htm")
FIXTURE_CPP_CN = os.path.join(os.path.dirname(__file__), "fixtures", "cpp_cb2234049_cn.html")
FIXTURE_CPP_EN = os.path.join(os.path.dirname(__file__), "fixtures", "cpp_cb2234049_en.html")


class StructureResolveTests(unittest.TestCase):
    """resolve_structure: 页面三件优先, mol 兜底, 脏数据整字段丢弃。"""

    @classmethod
    def setUpClass(cls) -> None:
        # E7: 样本在库(repo-relative), 缺失即失败 —— 不再把路径问题 skip 掉
        if not os.path.exists(FIXTURE_HTML):
            raise AssertionError(f"仓库 fixture 缺失: {FIXTURE_HTML}")
        # 旧 parse_entry 已退役(0905); fixture CAS 页不解析,
        # props 直接用 canonical 形态内联(结构三件解析的判别逻辑不变)
        cls.entry = {
            "props": [
                {"key": "smiles", "label": "SMILES", "text": "OC(=O)c1ccccc1"},
                {"key": "inchikey", "label": "InChIKey", "text": "WPYMKLBDIGXBTP-UHFFFAOYSA-N"},
                {"key": "density", "label": "密度", "text": "1.32 g/cm3"},
            ]
        }
        cls.molblock = open(FIXTURE, encoding="utf-8", errors="replace").read()

    def test_page_trio_present_in_props(self) -> None:
        """页面三件套被 props 捕获(canonical key: smiles/inchikey)。"""
        from api.services.cb import _props_field

        self.assertEqual(_props_field(self.entry, "smiles"), "OC(=O)c1ccccc1")
        self.assertEqual(
            _props_field(self.entry, "inchikey"), "WPYMKLBDIGXBTP-UHFFFAOYSA-N"
        )

    def test_resolve_structure_full(self) -> None:
        """真实 fixture: smiles 取页面值(规范化), inchikey 页面, mol 原文。"""
        from api.services.cb import resolve_structure

        s = resolve_structure(self.entry, self.molblock)
        self.assertEqual(s["smiles"], "O=C(O)c1ccccc1")
        self.assertEqual(s["inchikey"], "WPYMKLBDIGXBTP-UHFFFAOYSA-N")
        self.assertEqual(s["mol"], self.molblock)

    def test_resolve_structure_mol_fallback(self) -> None:
        """页面无三件(如 mol 404 条目): smiles/inchikey 从 mol 派生。"""
        from api.services.cb import resolve_structure

        entry = {"props": [{"key": "logp", "label": "LogP", "text": "1.87"}]}  # 无三件
        s = resolve_structure(entry, self.molblock)
        self.assertEqual(s["smiles"], "O=C(O)c1ccccc1")
        self.assertEqual(s["inchikey"], "WPYMKLBDIGXBTP-UHFFFAOYSA-N")
        self.assertEqual(s["mol"], self.molblock)

    def test_resolve_structure_garbage_smiles_dropped(self) -> None:
        """页面 SMILES 非标(RDKit 解析不过): 整字段丢弃, 从 mol 兜底, 不写脏值。"""
        from api.services.cb import resolve_structure

        entry = {"props": [{"key": "smiles", "label": "SMILES", "text": "这不是smiles%%"}, {"key": "inchikey", "label": "InChIKey", "text": "BAD-KEY"}]}
        s = resolve_structure(entry, self.molblock)
        self.assertEqual(s["smiles"], "O=C(O)c1ccccc1")  # mol 兜底
        self.assertEqual(s["inchikey"], "BAD-KEY")  # inchikey 无 mol 外校验, 原样(补空语义)

    def test_resolve_structure_all_absent(self) -> None:
        """三源全无: 全 None, 建行照常(无结构行, 不炸)。"""
        from api.services.cb import resolve_structure

        s = resolve_structure({"props": []}, None)
        self.assertEqual(s, {"smiles": None, "inchikey": None, "mol": None})

    def test_resolve_structure_garbage_mol_dropped(self) -> None:
        """mol 文件畸形: mol 原文丢弃, 派生兜底为 None, 页面三件不受影响。"""
        from api.services.cb import resolve_structure

        entry = {"props": [{"key": "smiles", "label": "SMILES", "text": "OC(=O)c1ccccc1"}]}
        s = resolve_structure(entry, "garbage not a molfile")
        self.assertEqual(s["smiles"], "O=C(O)c1ccccc1")  # 规范化后形式
        self.assertIsNone(s["mol"])


class CppParseTests(unittest.TestCase):
    """CPP 页解析(fixtures: CB2234049 CN/EN, 2026-09-19 实拉, CN 100家供应商)。"""

    @classmethod
    def setUpClass(cls) -> None:
        # E7: 原先读 /tmp 预置 CPP 页 → 样本入库, 缺失即失败(不 skip)
        for p in (FIXTURE_CPP_CN, FIXTURE_CPP_EN):
            if not os.path.exists(p):
                raise AssertionError(f"仓库 fixture 缺失: {p}")
        with open(FIXTURE_CPP_CN, encoding="utf-8", errors="replace") as fh:
            cls.html = fh.read()
        with open(FIXTURE_CPP_EN, encoding="utf-8", errors="replace") as fh:
            cls.html_en = fh.read()

    def test_cpp_suppliers_hundred_rows(self) -> None:
        from caslib.parse import parse_cpp_suppliers

        rows = parse_cpp_suppliers(self.html)
        self.assertEqual(len(rows), 100)
        by_locale = {}
        for r in rows:
            by_locale[r["locale"]] = by_locale.get(r["locale"], 0) + 1
        self.assertEqual(by_locale.get("中国"), 93)
        self.assertIn("德国", by_locale)
        # 首行字段齐全
        first = rows[0]
        self.assertEqual(first["name"], "南京苏如化工有限公司")
        self.assertEqual(first["email"], "sales@suruchem.com")
        self.assertRegex(first["cbsid"], r"^\d+$")
        # ref 契约 = "cb-supplier:" + cbsid(2026-09-19 样本 cbsid=1436986 → 19 字符;
        # 0905 样本的 16 是当时 cbsid 位数更短, 非契约常量)
        self.assertEqual(first["ref"], "cb-supplier:" + first["cbsid"])

    def test_cpp_suppliers_empty_or_garbage(self) -> None:
        from caslib.parse import parse_cpp_suppliers

        self.assertEqual(parse_cpp_suppliers(""), [])
        self.assertEqual(parse_cpp_suppliers("<html>无关页面</html>"), [])
        # EN 语言页供应商链接形态不同(/0_EN.htm), 不误配
        self.assertEqual(parse_cpp_suppliers(self.html_en), [])



if __name__ == "__main__":
    unittest.main()
