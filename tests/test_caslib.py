"""caslib 测试 — fixture 驱动(~/ops/cb-fixtures/, 仓库外, 不入库)。

真实网络路径不在单测里跑(见 DEVLOG 端到端验证记录):
ok / not_found / error 三态已人工实测(2026-08-25)。
"""
from __future__ import annotations

import json
import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from caslib.parse import (  # noqa: E402
    extract_cb_number,
    looks_like_not_found,
    parse_entry,
    parse_suppliers,
)
from caslib.redact import supplier_ref  # noqa: E402

FIXTURES = os.path.expanduser("~/ops/cb-fixtures")


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


class EntryParseTests(unittest.TestCase):
    def test_structure_ordered(self) -> None:
        if not _have_fixtures():
            self.skipTest("fixtures 不在本机")
        entry = parse_entry(_fixture("CAS_65-85-0.htm"))
        self.assertEqual(
            list(entry.keys()),
            ["basic", "aliases", "props", "safety", "prose", "updown", "reagents"],
        )
        # basic: 保序 KV, MOL 文件行被剔除
        keys = [k for k, _ in entry["basic"]]
        self.assertEqual(keys[0], "中文名称")
        self.assertNotIn("MOL 文件", keys)
        self.assertIn(["英文名称", "Benzoic acid"], entry["basic"])
        # props/safety 非空 KV
        self.assertTrue(entry["props"] and isinstance(entry["props"][0], list))
        self.assertTrue(entry["safety"] and isinstance(entry["safety"][0], list))
        # prose 小节
        titles = [p["title"] for p in entry["prose"]]
        self.assertIn("用途一", titles)
        self.assertIn("方法一", titles)
        # updown
        self.assertEqual(entry["updown"]["up"][0], "甲苯")
        self.assertTrue(entry["updown"]["down"])
        # reagents 两行文本不被压扁丢失
        self.assertTrue(any("Acros" in r["vendor"] for r in entry["reagents"]))

    def test_aliases_split(self) -> None:
        if not _have_fixtures():
            self.skipTest("fixtures 不在本机")
        entry = parse_entry(_fixture("CAS_65-85-0.htm"))
        self.assertIn("安息香酸", entry["aliases"]["cn"])
        self.assertTrue(entry["aliases"]["en"])


class SupplierTests(unittest.TestCase):
    def test_merge_and_redaction(self) -> None:
        if not _have_fixtures():
            self.skipTest("fixtures 不在本机")
        cas_html = _fixture("CAS_65-85-0.htm")
        sup_html = _fixture("Supplier_CB8698780.htm")
        suppliers = parse_suppliers(cas_html, sup_html)
        self.assertGreaterEqual(len(suppliers), 17)
        aladdin = next(s for s in suppliers if "阿拉丁" in s["name"])
        # CAS 页产品介绍字段
        self.assertTrue(aladdin["purity"])
        self.assertTrue(aladdin["pack_price"])
        # 专用页合并字段
        self.assertTrue(aladdin["email"])
        self.assertTrue(aladdin["website"])
        self.assertNotIn("chemicalbook", aladdin["website"].lower())
        # ref 为 16hex 不透明值
        self.assertEqual(len(aladdin["ref"]), 16)
        int(aladdin["ref"], 16)
        # 电话全量
        self.assertTrue(all(s["phone"] for s in suppliers))

    def test_cb_number_extract(self) -> None:
        if not _have_fixtures():
            self.skipTest("fixtures 不在本机")
        self.assertEqual(extract_cb_number(_fixture("CAS_65-85-0.htm")), "8698780")


class RedactTests(unittest.TestCase):
    def test_supplier_ref_stable(self) -> None:
        self.assertEqual(supplier_ref("10287"), supplier_ref(10287))
        self.assertNotEqual(supplier_ref("10287"), supplier_ref("10288"))


class BrandLeakTests(unittest.TestCase):
    def test_zero_brand_leak(self) -> None:
        if not _have_fixtures():
            self.skipTest("fixtures 不在本机")
        for cas in ("65-85-0", "69-72-7", "77-92-9"):
            h = _fixture(f"CAS_{cas}.htm")
            blob = json.dumps(parse_entry(h), ensure_ascii=False)
            blob += json.dumps(parse_suppliers(h, None), ensure_ascii=False)
            self.assertNotIn("chemicalbook", blob.lower(), cas)


if __name__ == "__main__":
    unittest.main()
