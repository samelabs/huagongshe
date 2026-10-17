"""供应商编号(cbsid)不出公开详情 — 对外 ref 用 caslib/redact.supplier_ref。

泄漏链路(修复前): caslib/parse 生成 ref="cb-supplier:{cbsid}" → 库内
chemical_supplier_profile.ref → get_suppliers 原样输出 → REST 详情
suppliers.items[].ref 内嵌原站供应商编号。修复只动 get_suppliers 出口:
库内键与数据不变。
"""
from __future__ import annotations

import asyncio
import json
import unittest
from types import SimpleNamespace


def _row(cbsid="1436986", name="SupA"):
    return SimpleNamespace(
        cbsid=cbsid, name=name, phone="1", email="a@b.c",
        website=None, purity="99%", pack_price="1L/10", remark=None,
    )


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _Db:
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, *_a, **_k):
        return _Result(self._rows)


class GetSuppliersRefRedactionTests(unittest.TestCase):
    def test_ref_is_opaque_hash_not_raw_identity(self):
        from api.services import cb as cb_module
        from caslib.redact import supplier_ref

        out = asyncio.run(cb_module.get_suppliers(_Db([_row()]), 1))
        self.assertEqual(out[0]["ref"], supplier_ref("1436986"))
        self.assertNotIn("cb-supplier:", out[0]["ref"])

    def test_output_contains_no_cbsid_key_or_value(self):
        from api.services import cb as cb_module

        out = asyncio.run(cb_module.get_suppliers(_Db([_row(cbsid="93086")]), 1))
        dumped = json.dumps(out, ensure_ascii=False)
        self.assertNotIn("cbsid", dumped)
        self.assertNotIn("93086", dumped)

    def test_output_keys_stable_no_identity_key_added(self):
        from api.services import cb as cb_module

        out = asyncio.run(cb_module.get_suppliers(_Db([_row()]), 1))
        self.assertEqual(
            set(out[0]),
            {"ref", "name", "phone", "email", "website",
             "purity", "pack_price", "remark"},
        )


class SemanticDetailPassThroughTests(unittest.TestCase):
    """REST 详情的 suppliers.items 直接承载 get_suppliers 行 — 源头脱标识
    即整链脱标识(REST 输出与 MCP full 输入同源)。"""

    def test_semantic_suppliers_carry_hashed_ref_only(self):
        from api.services.chemical_semantic import build_semantic_detail
        from caslib.redact import supplier_ref

        suppliers = [{
            "ref": supplier_ref("1436986"), "name": "SupA", "phone": "1",
            "email": "a@b.c", "website": None, "purity": "99%",
            "pack_price": "1L/10", "remark": None,
        }]
        detail = build_semantic_detail(None, None, suppliers, "current", "current")
        dumped = json.dumps(detail, ensure_ascii=False)
        self.assertNotIn("cbsid", dumped)
        self.assertNotIn("cb-supplier:", dumped)
        self.assertEqual(detail["suppliers"]["items"], suppliers)


if __name__ == "__main__":
    unittest.main()
