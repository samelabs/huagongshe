"""name_index 摄入与检索机制测试。

运行: ./venv/bin/python -m unittest tests.test_name_index -v
依赖: 本地 PG(huagongshe)。全部使用一次性哨兵行(TEST_ID 每次删除重建),
不触碰线上化合物数据。
"""
from __future__ import annotations

import asyncio
import json
import os
import unittest

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from api.services.name_index import (
    ingest_chemical_names,
    ingest_from_entry_cn,
    ingest_from_synonyms,
    normalize_name,
)

# 一次性哨兵行: 挂在 chemicals 表尾之外的自增 id 上, 不对应任何真实化合物,
# 每个测试 setUp 删旧建新, tearDown 清光。生产数据零接触。
SETUP_SQL = """
INSERT INTO chemistry.chemicals
  (id, smiles, molecular_formula, average_mass, monoisotopic_mass,
   inchikey, mol, morgan_bfp, morgan_sfp, preferred_name, iupac_name, created_at, updated_at)
VALUES
  (:id, 'CCO', 'C2H6O', 46.07, 46.0419, 'LFQSCWFLJHTTHZ-UHFFFAOYSA-N',
   mol_from_smiles('CCO'), morganbv_fp(mol_from_smiles('CCO')), morgan_fp(mol_from_smiles('CCO')),
   '测试乙醇哨兵', 'ethanol-test', now(), now())
ON CONFLICT (id) DO UPDATE SET preferred_name='测试乙醇哨兵', iupac_name='ethanol-test'
"""


def _engine():
    # 0909 测试库闸: 只认 TEST_DATABASE_URL 过闸值, 不再读 HGS_DATABASE_URL
    from tests.db_gate import require_test_db, ProductionDbBlocked
    try:
        url = require_test_db()
    except ProductionDbBlocked:
        raise unittest.SkipTest("需要测试库 (TEST_DATABASE_URL 过闸)")
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url.split("://", 1)[1]
    url = url.split("?", 1)[0]
    return create_async_engine(url)


async def _alloc_sentinel_id(conn) -> int:
    """复用一个固定高位 id 段(避开自增序列), 每次先清 name_index 再挂行。"""
    row = (await conn.execute(text(
        "SELECT greatest(coalesce(max(id),0), 100000000) + 1 FROM chemistry.chemicals"
    ))).scalar()
    sid = int(row)
    await conn.execute(text("DELETE FROM chemistry.name_index WHERE chemical_id=:i"), {"i": sid})
    await conn.execute(text(SETUP_SQL), {"id": sid})
    return sid


class NormalizeTest(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(normalize_name("  苯甲酸 "), "苯甲酸")
        self.assertEqual(normalize_name("Benzoic   Acid"), "benzoic acid")
        self.assertEqual(normalize_name("\tX\nY\t"), "x y")


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "需要测试库 (TEST_DATABASE_URL)")
class IngestTest(unittest.TestCase):
    def run_coro(self, coro):
        return asyncio.run(coro)

    def test_replace_semantics_and_exclusion(self):
        async def body():
            eng = _engine()
            try:
                async with eng.begin() as conn:
                    sid = await _alloc_sentinel_id(conn)
                    n1 = await ingest_chemical_names(conn, sid, source="cb", items=[
                        ("name_cn", "cn", "哨兵名甲"),
                        ("name_cn", "cn", "测试乙醇哨兵"),  # == preferred_name, 排除
                        ("alias_cn", "cn", "哨兵别名"),
                        ("alias_cn", "cn", "哨兵别名"),  # 重复
                        ("alias_en", "en", "Sentinel Ol"),
                        ("alias_cn", "cn", "  "),  # 空 normalize
                    ])
                    rows = (await conn.execute(text(
                        "SELECT kind, normalized, name FROM chemistry.name_index"
                        " WHERE chemical_id=:i AND source='cb' ORDER BY kind, normalized"
                    ), {"i": sid})).fetchall()
                    n2 = await ingest_chemical_names(conn, sid, source="cb", items=[
                        ("alias_cn", "cn", "哨兵别名乙"),
                    ])
                    rows2 = (await conn.execute(text(
                        "SELECT kind, normalized FROM chemistry.name_index"
                        " WHERE chemical_id=:i AND source='cb'"
                    ), {"i": sid})).fetchall()
                    n3 = await ingest_chemical_names(conn, sid, source="cb", items=[])
                    rows3 = (await conn.execute(text(
                        "SELECT count(*) FROM chemistry.name_index"
                        " WHERE chemical_id=:i AND source='cb'"
                    ), {"i": sid})).scalar()
                    await conn.execute(text(
                        "DELETE FROM chemistry.name_index WHERE chemical_id=:i"), {"i": sid})
                    await conn.execute(text(
                        "DELETE FROM chemistry.chemicals WHERE id=:i"), {"i": sid})
                    return n1, [tuple(r) for r in rows], n2, [tuple(r) for r in rows2], n3, rows3
            finally:
                await eng.dispose()

        n1, rows1, n2, rows2, n3, count3 = self.run_coro(body())
        self.assertEqual(n1, 3)  # 哨兵名甲+哨兵别名+sentinel ol (排除1/重复1/空1)
        self.assertEqual(rows1, [
            ("alias_cn", "哨兵别名", "哨兵别名"),
            ("alias_en", "sentinel ol", "Sentinel Ol"),  # name 保留原始大小写
            ("name_cn", "哨兵名甲", "哨兵名甲"),
        ])
        self.assertEqual(n2, 1)
        self.assertEqual(rows2, [("alias_cn", "哨兵别名乙")])
        self.assertEqual(n3, 0)
        self.assertEqual(count3, 0)

    def test_ingest_from_entry_cn_mapping(self):
        async def body():
            eng = _engine()
            try:
                async with eng.begin() as conn:
                    sid = await _alloc_sentinel_id(conn)
                    entry = {
                        "identity": {"cn": "哨兵苯甲酸", "en": "Sentinel Acid",
                                     "alias_cn": ["哨兵安息香酸"], "alias_en": ["Sentinel Benzoate"]},
                    }
                    # I-055: 名称一律以表内 zh-CN ok 行为准(真实链路是
                    # cb.py 先 UPSERT chemical_cb 再同事务调镜像摄入)。
                    await conn.execute(text("""
                        INSERT INTO chemistry.chemical_cb
                          (chemical_id,cas_number,cb_number,entry,last_status,fetched_at,locale)
                        VALUES (:i,'7732-18-5','CBTEST01',
                                CAST(:entry AS jsonb),'ok',now(),'zh-CN')
                    """), {"i": sid, "entry": json.dumps(entry)})
                    await ingest_from_entry_cn(conn, sid, ["哨兵供应商甲", None])
                    rows = (await conn.execute(text(
                        "SELECT source, kind, lang, normalized FROM chemistry.name_index"
                        " WHERE chemical_id=:i ORDER BY kind"
                    ), {"i": sid})).fetchall()
                    # 行转 error(not_found/error 均不贡献数据)后再摄入 → 清空
                    await conn.execute(text(
                        "UPDATE chemistry.chemical_cb SET last_status='error'"
                        " WHERE chemical_id=:i"
                    ), {"i": sid})
                    await ingest_from_entry_cn(conn, sid, [])
                    after = (await conn.execute(text(
                        "SELECT count(*) FROM chemistry.name_index WHERE chemical_id=:i"
                    ), {"i": sid})).scalar()
                    await conn.execute(text(
                        "DELETE FROM chemistry.chemical_cb WHERE chemical_id=:i"), {"i": sid})
                    await conn.execute(text(
                        "DELETE FROM chemistry.chemicals WHERE id=:i"), {"i": sid})
                    return [tuple(r) for r in rows], after
            finally:
                await eng.dispose()

        rows, after = self.run_coro(body())
        kinds = {(r[1], r[2], r[3]) for r in rows}
        # 英文名称 basic 行不摄入(英文域=PubChem; CB 只贡献 中文名/别名/供应商)
        self.assertEqual(len(rows), 4)
        self.assertIn(("name_cn", "cn", "哨兵苯甲酸"), kinds)
        self.assertIn(("alias_cn", "cn", "哨兵安息香酸"), kinds)
        self.assertIn(("alias_en", "en", "sentinel benzoate"), kinds)
        self.assertIn(("supplier", "cn", "哨兵供应商甲"), kinds)
        self.assertEqual(after, 0)

    def test_cb_multi_record_names_are_union_regardless_of_refresh_order(self):
        """I-055: 同一化合物多条 zh-CN CB 记录, name_index 名称取并集且与刷新先后无关。"""

        async def refresh(conn, sid, cb_number, cn_name, alias):
            from api.services.cb import upsert_externals
            entry = {"identity": {"cn": cn_name, "alias_cn": [alias]}}
            await upsert_externals(
                conn, chemical_id=sid, cas_number="1000000-00-9",
                entry=entry, suppliers=[],
                status="ok", cb_number=cb_number, locale="zh-CN")

        def read_names(rows):
            return {r[1] for r in rows if r[0] == "cb"}

        async def body():
            eng = _engine()
            try:
                names_by_sentinel = []
                for order in (("CB001", "CB002"), ("CB002", "CB001")):
                    async with eng.begin() as conn:
                        sid = await _alloc_sentinel_id(conn)
                    for cb_number in order:
                        # 两条记录各自的中文名与别名互不重叠
                        async with eng.begin() as conn:
                            await refresh(conn, sid, cb_number,
                                          f"哨兵并集名{cb_number}", f"哨兵别名{cb_number}")
                    # 两次刷新都完成后读镜像: 必须是两行名称的并集
                    async with eng.begin() as conn:
                        rows = (await conn.execute(text(
                            "SELECT source, name FROM chemistry.name_index"
                            " WHERE chemical_id=:i AND kind IN ('name_cn','alias_cn')"
                        ), {"i": sid})).fetchall()
                    names_by_sentinel.append((sid, read_names(rows)))
                    # 清理本哨兵的全部痕迹
                    async with eng.begin() as conn:
                        await conn.execute(text(
                            "DELETE FROM chemistry.chemical_cb WHERE chemical_id=:i"), {"i": sid})
                        await conn.execute(text(
                            "DELETE FROM chemistry.chemicals WHERE id=:i"), {"i": sid})
                return names_by_sentinel
            finally:
                await eng.dispose()

        results = self.run_coro(body())
        expected = {"哨兵并集名CB001", "哨兵并集名CB002",
                    "哨兵别名CB001", "哨兵别名CB002"}
        for sid, names in results:
            self.assertEqual(
                names, expected,
                f"哨兵 {sid}: 两种刷新顺序都必须得到同一并集",
            )

    def test_ingest_from_synonyms_none_keeps(self):
        async def body():
            eng = _engine()
            try:
                async with eng.begin() as conn:
                    sid = await _alloc_sentinel_id(conn)
                    await ingest_chemical_names(conn, sid, source="pubchem", items=[
                        ("synonym_en", "en", "Kept Name")
                    ])
                    await ingest_from_synonyms(conn, sid, None)  # 不动
                    kept = (await conn.execute(text(
                        "SELECT count(*), max(name) FROM chemistry.name_index"
                        " WHERE chemical_id=:i AND source='pubchem'"
                    ), {"i": sid})).first()
                    await ingest_from_synonyms(conn, sid, ["Replaced Name"])
                    after = (await conn.execute(text(
                        "SELECT normalized, name FROM chemistry.name_index"
                        " WHERE chemical_id=:i AND source='pubchem'"
                    ), {"i": sid})).first()
                    await conn.execute(text(
                        "DELETE FROM chemistry.chemicals WHERE id=:i"), {"i": sid}
                    )
                    return kept, after
            finally:
                await eng.dispose()

        kept, after = self.run_coro(body())
        self.assertEqual(kept[0], 1)
        self.assertEqual(kept[1], "Kept Name")  # 原始大小写保留
        self.assertEqual(tuple(after), ("replaced name", "Replaced Name"))


if __name__ == "__main__":
    unittest.main()
