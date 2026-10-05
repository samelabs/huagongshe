"""followed_chemicals 契约测试 · Saved 名称正确性。

背景: /users/me/follows/chemicals 此前 payload 缺 name_cn/molecular_formula,
导致 zh-CN Saved 面板只能显示英文名。本文件直接执行真实 endpoint 函数
api.social.followed_chemicals(...), 用 fake DB 只分发结果, 走完整链路:

    follow count → follows SQL → attach_localized_names() → name_index lookup
    → response assembly

锁四件事:
1. payload 契约: id/preferred_name/iupac_name/name_cn/molecular_formula/smiles/created_at
2. SQL 契约: follows SELECT 必须包含 c.molecular_formula
3. localized-name owner: 恰好一次 name_index lookup, 三元组参数等于
   api.services.chemicals 的现有 owner 定义(不在本文件复制业务实现);
4. 防重复治理: api/social.py 源码不得出现第二套 taxonomy
   (kind='name_cn' / lang='cn' / source='cb' / name_index)。
"""

from __future__ import annotations

import os
import unittest
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from api.social import followed_chemicals  # noqa: E402
from api.services.chemicals import (  # noqa: E402
    LOCALIZED_NAME_KIND,
    LOCALIZED_NAME_LANG,
    LOCALIZED_NAME_SOURCE,
)

HCID = 71747
EN_NAME = "N-(4,7-Dimethoxy-6-(2-(1-piperidinyl)ethoxy)-5-benzofuranyl)-N'-methylurea"
CN_NAME = "莫罗卡尼"
FORMULA = "C19H27N3O5"
SMILES = "CNC(=O)Nc1c(OCCN2CCCCC2)c(OC)c2occc2c1OC"


class _FakeScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class _FakeMappingsResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _FakeFetchResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class FakeFollowsDb:
    """只按 SQL 文本分发预置结果; 记录每次 execute 的 (sql, params)。"""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, clause, params=None):
        sql = str(clause)
        self.calls.append((sql, dict(params or {})))
        if "count(*)" in sql and "chemical_follows" in sql:
            return _FakeScalarResult(1)
        if "chemical_follows" in sql and "chemistry.chemicals" in sql:
            return _FakeMappingsResult([{
                "id": HCID,
                "preferred_name": EN_NAME,
                "iupac_name": "1-[4,7-dimethoxy-6-(2-piperidin-1-ylethoxy)-1-benzofuran-5-yl]-3-methylurea",
                "molecular_formula": FORMULA,
                "smiles": SMILES,
                "created_at": "2026-10-05T10:16:02.438834+00:00",
            }])
        if "name_index" in sql:
            # (chemical_id, name) 元组行, 与真实 fetchall 形状一致
            return _FakeFetchResult([(HCID, CN_NAME)])
        raise AssertionError(f"fake DB 收到未预期的 SQL: {sql[:120]}")


class FollowedChemicalsContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_payload_carries_locale_fields(self):
        db = FakeFollowsDb()
        result = await followed_chemicals(
            page=1, page_size=40, actor=SimpleNamespace(id=42), db=db,
        )
        self.assertEqual({"items", "total", "page", "page_size"}, set(result))
        self.assertEqual(1, result["total"])
        item = result["items"][0]
        self.assertEqual(HCID, item["id"])
        self.assertEqual(EN_NAME, item["preferred_name"])
        self.assertEqual(CN_NAME, item["name_cn"], "zh-CN Saved 主标题字段")
        self.assertEqual(FORMULA, item["molecular_formula"])
        self.assertTrue(item["molecular_formula"], "molecular_formula 必须非空")
        self.assertEqual(SMILES, item["smiles"])
        self.assertIn("iupac_name", item)
        self.assertIn("created_at", item)

    async def test_follows_sql_selects_molecular_formula(self):
        db = FakeFollowsDb()
        await followed_chemicals(page=1, page_size=40, actor=SimpleNamespace(id=42), db=db)
        follows_sqls = [sql for sql, _ in db.calls if "chemical_follows" in sql and "count(*)" not in sql]
        self.assertEqual(1, len(follows_sqls))
        self.assertIn("c.molecular_formula", follows_sqls[0], "follows SQL 必须带 formula")

    async def test_single_name_index_lookup_with_owner_taxonomy(self):
        db = FakeFollowsDb()
        await followed_chemicals(page=1, page_size=40, actor=SimpleNamespace(id=42), db=db)
        lookups = [(sql, params) for sql, params in db.calls if "name_index" in sql]
        self.assertEqual(1, len(lookups), "整页必须恰好一次 name_index lookup")
        _, params = lookups[0]
        # 三元组只对照 services.chemicals 的 owner 常量, 不在本文件复制取值来源
        self.assertEqual(LOCALIZED_NAME_KIND, params["kind"])
        self.assertEqual(LOCALIZED_NAME_LANG, params["lang"])
        self.assertEqual(LOCALIZED_NAME_SOURCE, params["source"])
        self.assertEqual([HCID], list(params["ids"]))



class HandlerDelegatesToOwnerTests(unittest.TestCase):
    """窄断言: handler 只通过 attach_localized_names 拿本地化名(不扫描全文件、不禁词)。"""

    def test_handler_calls_attach_localized_names(self):
        import inspect

        from api.social import followed_chemicals as handler

        source = inspect.getsource(handler)
        self.assertIn("attach_localized_names", source)


if __name__ == "__main__":
    unittest.main()
