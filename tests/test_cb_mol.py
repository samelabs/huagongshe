"""CB mol 拉取/解析的判别与行为测试(fixture: benzoic acid 65-85-0, 2026-08-28 实拉)."""
from __future__ import annotations

import os
import unittest

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "cb_65850.mol")
FIXTURE_HTML = os.path.join(os.path.dirname(__file__), "fixtures", "CAS_65-85-0.htm")


class MolFetchTests(unittest.TestCase):
    def test_mol_href_extract_present(self) -> None:
        from caslib.parse import extract_mol_href

        html = '<span>MOL 文件</span><a title="65-85-0_MolFile" href="/CAS/mol/65-85-0.mol">65-85-0.mol</a>'
        self.assertEqual(extract_mol_href(html), "/CAS/mol/65-85-0.mol")

    def test_mol_href_extract_absent(self) -> None:
        from caslib.parse import extract_mol_href

        self.assertIsNone(extract_mol_href("<html><body>无外链</body></html>"))

    def test_mol_href_extract_real_fixture(self) -> None:
        from caslib.parse import extract_mol_href

        if not os.path.exists(FIXTURE_HTML):
            self.skipTest("fixtures 不在本机")
        with open(FIXTURE_HTML, encoding="utf-8", errors="replace") as fh:
            html = fh.read()
        self.assertEqual(extract_mol_href(html), "/CAS/mol/65-85-0.mol")

    def test_molfile_validity_check(self) -> None:
        from caslib.fetch import looks_like_molfile

        if not os.path.exists(FIXTURE):
            self.skipTest("fixtures 不在本机")
        with open(FIXTURE, encoding="utf-8", errors="replace") as fh:
            body = fh.read()
        self.assertTrue(looks_like_molfile(body))
        self.assertFalse(looks_like_molfile("<!DOCTYPE html><html>404页</html>"))
        self.assertFalse(looks_like_molfile(""))
        self.assertFalse(looks_like_molfile("M  END"))

    def test_molfile_rdkit_parse(self) -> None:
        """真实 CB molfile 必须能被 RDKit 解析出苯甲酸. 化学人直觉判据."""
        if not os.path.exists(FIXTURE):
            self.skipTest("fixtures 不在本机")
        with open(FIXTURE, encoding="utf-8", errors="replace") as fh:
            body = fh.read()
        from rdkit import Chem

        mol = Chem.MolFromMolBlock(body, sanitize=True, removeHs=True)
        self.assertIsNotNone(mol)
        self.assertEqual(mol.GetNumAtoms(), 9)  # C7H6O2 重原子 9
        smiles = Chem.MolToSmiles(mol)
        self.assertEqual(smiles, "O=C(O)c1ccccc1")
        self.assertEqual(Chem.MolToInchiKey(mol), "WPYMKLBDIGXBTP-UHFFFAOYSA-N")

    def test_molblock_normalization(self) -> None:
        """BOM/CRLF/前置空白清洗, 不改内容."""
        from caslib.fetch import normalize_molblock

        self.assertEqual(normalize_molblock("  \ufeffline1\r\nline2\r\n"), "line1\nline2\n")


class StructureResolveTests(unittest.TestCase):
    """resolve_structure: 页面三件优先, mol 兜底, 脏数据整字段丢弃。"""

    @classmethod
    def setUpClass(cls) -> None:
        if not os.path.exists(FIXTURE_HTML):
            raise unittest.SkipTest("fixtures 不在本机")
        from caslib.parse import parse_entry

        html = open(FIXTURE_HTML, encoding="utf-8", errors="replace").read()
        cls.entry = parse_entry(html)
        cls.molblock = open(FIXTURE, encoding="utf-8", errors="replace").read()

    def test_page_trio_present_in_props(self) -> None:
        """页面三件套被 props 捕获(物理化学性质区 xztr)。"""
        from api.cas_externals import _props_field

        self.assertEqual(_props_field(self.entry, "SMILES"), "OC(=O)c1ccccc1")
        self.assertEqual(
            _props_field(self.entry, "InChIKey"), "WPYMKLBDIGXBTP-UHFFFAOYSA-N"
        )

    def test_resolve_structure_full(self) -> None:
        """真实 fixture: smiles 取页面值(规范化), inchikey 页面, mol 原文。"""
        from api.cas_externals import resolve_structure

        s = resolve_structure(self.entry, self.molblock)
        self.assertEqual(s["smiles"], "O=C(O)c1ccccc1")
        self.assertEqual(s["inchikey"], "WPYMKLBDIGXBTP-UHFFFAOYSA-N")
        self.assertEqual(s["mol"], self.molblock)

    def test_resolve_structure_mol_fallback(self) -> None:
        """页面无三件(如 mol 404 条目): smiles/inchikey 从 mol 派生。"""
        from api.cas_externals import resolve_structure

        entry = {"props": [["LogP", "1.87"]]}  # 无三件
        s = resolve_structure(entry, self.molblock)
        self.assertEqual(s["smiles"], "O=C(O)c1ccccc1")
        self.assertEqual(s["inchikey"], "WPYMKLBDIGXBTP-UHFFFAOYSA-N")
        self.assertEqual(s["mol"], self.molblock)

    def test_resolve_structure_garbage_smiles_dropped(self) -> None:
        """页面 SMILES 非标(RDKit 解析不过): 整字段丢弃, 从 mol 兜底, 不写脏值。"""
        from api.cas_externals import resolve_structure

        entry = {"props": [["SMILES", "这不是smiles%%"], ["InChIKey", "BAD-KEY"]]}
        s = resolve_structure(entry, self.molblock)
        self.assertEqual(s["smiles"], "O=C(O)c1ccccc1")  # mol 兜底
        self.assertEqual(s["inchikey"], "BAD-KEY")  # inchikey 无 mol 外校验, 原样(补空语义)

    def test_resolve_structure_all_absent(self) -> None:
        """三源全无: 全 None, 建行照常(无结构行, 不炸)。"""
        from api.cas_externals import resolve_structure

        s = resolve_structure({"props": []}, None)
        self.assertEqual(s, {"smiles": None, "inchikey": None, "mol": None})

    def test_resolve_structure_garbage_mol_dropped(self) -> None:
        """mol 文件畸形: mol 原文丢弃, 派生兜底为 None, 页面三件不受影响。"""
        from api.cas_externals import resolve_structure

        entry = {"props": [["SMILES", "OC(=O)c1ccccc1"]]}
        s = resolve_structure(entry, "garbage not a molfile")
        self.assertEqual(s["smiles"], "O=C(O)c1ccccc1")  # 规范化后形式
        self.assertIsNone(s["mol"])


class SupplierIdentityTests(unittest.TestCase):
    """供应商/条目身份标识: cbsid 与 cb_number 保留进结构化产物(落DB)。"""

    @classmethod
    def setUpClass(cls) -> None:
        if not os.path.exists(FIXTURE_HTML):
            raise unittest.SkipTest("fixtures 不在本机")

    def test_caspage_supplier_id_full_coverage(self) -> None:
        """真实 fixture: CAS 页链接 ID 提取, 供应商 100% 带 cbsid(18/18)。"""
        from caslib.parse import parse_suppliers

        suppliers = parse_suppliers(
            open(FIXTURE_HTML, encoding="utf-8", errors="replace").read(), None
        )
        self.assertTrue(suppliers)
        with_id = [s for s in suppliers if s.get("cbsid")]
        self.assertEqual(len(with_id), len(suppliers))
        # ref 由 cbsid 派生(不再用名称哈希)
        for s in with_id:
            self.assertNotIn("name:", s["ref"])
        # 阿拉丁实测 cbsid=10287
        sample = [s for s in suppliers if "阿拉丁" in s["name"]]
        if sample:
            self.assertEqual(sample[0]["cbsid"], "10287")

    def test_merge_caspage_id_not_overwritten(self) -> None:
        """专用页 cbsid 与 CAS 页不一致时不覆盖(CAS 页链接 ID 为主)。"""
        from caslib.parse import merge_suppliers

        cas_page = {"甲公司": {"ref": "r1", "cbsid": "111", "name": "甲公司",
                          "phone": None, "email": None, "website": None,
                          "purity": None, "pack_price": None, "remark": None}}
        dedicated = {"甲公司": {"cbsid": "999", "email": "a@b.c"}}
        merged = merge_suppliers(cas_page, dedicated)
        self.assertEqual(merged[0]["cbsid"], "111")  # 主路径不被二跳覆盖
        self.assertEqual(merged[0]["email"], "a@b.c")  # 增强字段照常合并

    def test_merge_dedicated_fills_missing(self) -> None:
        """CAS 页无 ID 时专用页兜底回填。"""
        from caslib.parse import merge_suppliers

        cas_page = {"乙公司": {"ref": None, "cbsid": None, "name": "乙公司",
                           "phone": "123", "email": None, "website": None,
                           "purity": None, "pack_price": None, "remark": None}}
        dedicated = {"乙公司": {"cbsid": "777", "email": "x@y.z"}}
        merged = merge_suppliers(cas_page, dedicated)
        self.assertEqual(merged[0]["cbsid"], "777")


class CppParseTests(unittest.TestCase):
    """CPP 页解析(fixture: 2026-08-28 实拉 NBS CB2234049, 100家供应商)。"""

    @classmethod
    def setUpClass(cls) -> None:
        path = "/tmp/cpp_CN.htm"
        if not os.path.exists(path):
            raise unittest.SkipTest("CPP fixture 不在本机")
        cls.html = open(path, encoding="utf-8", errors="replace").read()
        cls.html_en = open("/tmp/cpp_EN.htm", encoding="utf-8",
                           errors="replace").read() if os.path.exists("/tmp/cpp_EN.htm") else ""

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
        self.assertEqual(len(first["ref"]), 16)

    def test_cpp_suppliers_empty_or_garbage(self) -> None:
        from caslib.parse import parse_cpp_suppliers

        self.assertEqual(parse_cpp_suppliers(""), [])
        self.assertEqual(parse_cpp_suppliers("<html>无关页面</html>"), [])
        # EN 语言页供应商链接形态不同(/0_EN.htm), 不误配
        if self.html_en:
            self.assertEqual(parse_cpp_suppliers(self.html_en), [])

    def test_cpp_entry_full(self) -> None:
        from caslib.parse import parse_cpp_entry

        entry = parse_cpp_entry(self.html)
        self.assertIsNotNone(entry)
        keys = set(entry.keys())
        self.assertIn("basic", keys)
        self.assertIn("props", keys)
        self.assertIn("safety", keys)
        self.assertIn("prose", keys)
        self.assertIn("updown", keys)
        self.assertIn("reagent_prices", keys)
        self.assertIn("global_distribution", keys)
        # basic 键值抽查
        basic = dict(entry["basic"])
        self.assertEqual(basic.get("CAS号"), "128-08-5")
        self.assertEqual(basic.get("英文名"), "N-Bromosuccinimide")
        # props: 熔点
        props = dict(entry["props"])
        self.assertIn("175-180", props.get("熔点", ""))
        # safety: 14 对
        self.assertEqual(len(entry["safety"]), 14)
        # 全球分布
        gd = entry["global_distribution"]
        self.assertEqual(gd["total"], 1050)
        self.assertEqual(gd["countries"].get("中国"), 781)

    def test_cpp_entry_en(self) -> None:
        if not self.html_en:
            self.skipTest("EN fixture 不在本机")
        from caslib.parse import parse_cpp_entry_en

        entry = parse_cpp_entry_en(self.html_en)
        self.assertIsNotNone(entry)
        attrs = dict(entry["attributes"])
        self.assertIn("SMILES", attrs)
        self.assertIn("InChI", attrs)


if __name__ == "__main__":
    unittest.main()
