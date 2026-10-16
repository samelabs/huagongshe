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
    ingest_from_cb_locales,
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

    def test_ingest_from_cb_locales_mapping(self):
        async def body():
            eng = _engine()
            try:
                async with eng.begin() as conn:
                    sid = await _alloc_sentinel_id(conn)
                    entry = {
                        "identity": {"cn": "哨兵苯甲酸", "en": "Sentinel Acid",
                                     "alias_cn": ["哨兵安息香酸"], "alias_en": ["Sentinel Benzoate"]},
                    }
                    # I-055/I-087: 名称一律以表内全部 locale ok 行为准
                    # (真实链路是 cb.py 先 UPSERT chemical_cb 再同事务调镜像摄入)。
                    await conn.execute(text("""
                        INSERT INTO chemistry.chemical_cb
                          (chemical_id,cas_number,cb_number,entry,last_status,fetched_at,locale)
                          VALUES (:i,'7732-18-5','CBTEST01',
                                  CAST(:entry AS jsonb),'ok',now(),'zh-CN')
                    """), {"i": sid, "entry": json.dumps(entry)})
                    # I-087: supplier 名镜像 listing ⋈ profile(不再由调用方传入)
                    await conn.execute(text("""
                        INSERT INTO chemistry.chemical_supplier_profile
                          (cbsid,name) VALUES ('TESTSUP01','哨兵供应商甲')
                        ON CONFLICT (cbsid) DO UPDATE SET name=excluded.name
                    """))
                    await conn.execute(text("""
                        INSERT INTO chemistry.chemical_supplier_listing
                          (chemical_id,cbsid) VALUES (:i,'TESTSUP01')
                        ON CONFLICT (chemical_id, cbsid) DO NOTHING
                    """), {"i": sid})
                    await ingest_from_cb_locales(conn, sid)
                    rows = (await conn.execute(text(
                        "SELECT source, kind, lang, normalized FROM chemistry.name_index"
                        " WHERE chemical_id=:i ORDER BY kind"
                    ), {"i": sid})).fetchall()
                    # 行转 error(not_found/error 均不贡献数据)后再摄入 → 名称清空;
                    # supplier 随 listing 镜像保留(error 不删 listing 行)。
                    await conn.execute(text(
                        "UPDATE chemistry.chemical_cb SET last_status='error'"
                        " WHERE chemical_id=:i"
                    ), {"i": sid})
                    await ingest_from_cb_locales(conn, sid)
                    after = (await conn.execute(text(
                        "SELECT kind FROM chemistry.name_index WHERE chemical_id=:i"
                    ), {"i": sid})).scalars().all()
                    await conn.execute(text(
                        "DELETE FROM chemistry.chemical_cb WHERE chemical_id=:i"), {"i": sid})
                    await conn.execute(text(
                        "DELETE FROM chemistry.chemicals WHERE id=:i"), {"i": sid})
                    return [tuple(r) for r in rows], set(after)
            finally:
                await eng.dispose()

        rows, after_kinds = self.run_coro(body())
        kinds = {(r[1], r[2], r[3]) for r in rows}
        # 英文名称 basic 行不摄入(英文域=PubChem; CB 只贡献 各语言名/别名/供应商)
        self.assertEqual(len(rows), 4)
        self.assertIn(("name_cn", "cn", "哨兵苯甲酸"), kinds)
        self.assertIn(("alias_cn", "cn", "哨兵安息香酸"), kinds)
        self.assertIn(("alias_en", "en", "sentinel benzoate"), kinds)
        self.assertIn(("supplier", "cn", "哨兵供应商甲"), kinds)
        self.assertEqual(after_kinds, {"supplier"})

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

    def test_cb_multilocale_names_union_order_independent_and_error_removal(self):
        """I-087: 多 locale 名称并集, 刷新顺序无关; 某 locale 转 error 后其名称移除。"""

        async def refresh(conn, sid, cb_number, locale, cn_name, alias):
            from api.services.cb import upsert_externals
            entry = {"identity": {"cn": cn_name, "alias_cn": [alias]}}
            await upsert_externals(
                conn, chemical_id=sid, cas_number="1000000-00-9",
                entry=entry, suppliers=[],
                status="ok", cb_number=cb_number, locale=locale)

        async def read_names(conn, sid):
            rows = (await conn.execute(text(
                "SELECT kind, lang, name FROM chemistry.name_index"
                " WHERE chemical_id=:i AND source='cb'"
            ), {"i": sid})).fetchall()
            return {(r[0], r[1], r[2]) for r in rows}

        async def body():
            eng = _engine()
            try:
                locale_rows = [
                    ("CB9001", "zh-CN", "哨兵丙酮", "哨兵二甲基酮"),
                    ("CB9002", "ja", "アセトアセトアミド哨兵", "ジアセチルアミド哨兵"),
                    ("CB9003", "ko", "아세토아세트아미드哨兵", "다이아세틸아미드哨兵"),
                    ("CB9004", "de", "Acetessigsäureamid-Sentinel", "Diacetylamid-Sentinel"),
                ]
                results = []
                # 两种刷新顺序(首尾颠倒)都必须得到同一并集
                for order in (locale_rows, list(reversed(locale_rows))):
                    async with eng.begin() as conn:
                        sid = await _alloc_sentinel_id(conn)
                    for cb_number, locale, cn, alias in order:
                        async with eng.begin() as conn:
                            await refresh(conn, sid, cb_number, locale, cn, alias)
                    async with eng.begin() as conn:
                        results.append((sid, await read_names(conn, sid)))
                    # ja 行转 error → 重建后 ja 名称移除, 其余 locale 保留
                    async with eng.begin() as conn:
                        await conn.execute(text(
                            "UPDATE chemistry.chemical_cb SET last_status='error'"
                            " WHERE chemical_id=:i AND locale='ja'"), {"i": sid})
                        await ingest_from_cb_locales(conn, sid)
                        results.append((sid, "after", await read_names(conn, sid)))
                    async with eng.begin() as conn:
                        await conn.execute(text(
                            "DELETE FROM chemistry.chemical_cb WHERE chemical_id=:i"), {"i": sid})
                        await conn.execute(text(
                            "DELETE FROM chemistry.chemicals WHERE id=:i"), {"i": sid})
                return results
            finally:
                await eng.dispose()

        results = self.run_coro(body())
        expected_union = {
            ("name_cn", "cn", "哨兵丙酮"),
            ("alias_cn", "cn", "哨兵二甲基酮"),
            ("name_cn", "ja", "アセトアセトアミド哨兵"),
            ("alias_cn", "ja", "ジアセチルアミド哨兵"),
            ("name_cn", "ko", "아세토아세트아미드哨兵"),
            ("alias_cn", "ko", "다이아세틸아미드哨兵"),
            ("name_cn", "de", "Acetessigsäureamid-Sentinel"),
            ("alias_cn", "de", "Diacetylamid-Sentinel"),
        }
        expected_after_ja_error = expected_union - {
            ("name_cn", "ja", "アセトアセトアミド哨兵"),
            ("alias_cn", "ja", "ジアセチルアミド哨兵"),
        }
        for i in range(0, len(results), 2):
            sid, union = results[i]
            _, _, after = results[i + 1]
            self.assertEqual(union, expected_union,
                             f"哨兵 {sid}: 任意刷新顺序都必须得到同一多语言并集")
            self.assertEqual(after, expected_after_ja_error,
                             f"哨兵 {sid}: ja 行转 error 后其名称必须移除, 其余保留")

    def test_zh_cn_wins_when_ja_local_name_collides(self):
        """R4: 同一 cb_number 下 ja 当地名归一化后与中文名相同时,
        (name_cn, 'cn') 行必须保留 —— name_index 的 PK 不含 lang, 先处理
        的行先占主键; zh-CN 永远在每个 cb_number 内第一个处理。"""

        async def refresh(conn, sid, cb_number, locale, cn_name):
            from api.services.cb import upsert_externals
            entry = {"identity": {"cn": cn_name}}
            await upsert_externals(
                conn, chemical_id=sid, cas_number="1000000-00-9",
                entry=entry, suppliers=[],
                status="ok", cb_number=cb_number, locale=locale)

        async def body():
            eng = _engine()
            try:
                results = []
                # 两种落库顺序(ja 先 / zh-CN 先)结果必须一致
                for order in (("ja", "zh-CN"), ("zh-CN", "ja")):
                    async with eng.begin() as conn:
                        sid = await _alloc_sentinel_id(conn)
                    for locale in order:
                        async with eng.begin() as conn:
                            # 同一 cb_number, ja 与 zh-CN 当地名逐字相同
                            await refresh(conn, sid, "CB9500", locale,
                                          "哨兵碰撞名")
                    async with eng.begin() as conn:
                        rows = (await conn.execute(text(
                            "SELECT kind, lang, name FROM chemistry.name_index"
                            " WHERE chemical_id=:i AND source='cb'"
                        ), {"i": sid})).fetchall()
                        results.append((sid, {(r[0], r[1], r[2]) for r in rows}))
                    async with eng.begin() as conn:
                        await conn.execute(text(
                            "DELETE FROM chemistry.chemical_cb WHERE chemical_id=:i"),
                            {"i": sid})
                        await conn.execute(text(
                            "DELETE FROM chemistry.chemicals WHERE id=:i"),
                            {"i": sid})
                return results
            finally:
                await eng.dispose()

        results = self.run_coro(body())
        # 中文主标题行 (name_cn, 'cn') 必须存在(attach_localized_names 依赖
        # 该三元组); 归一化碰撞时 ja 行被 PK 冲突合并掉, 不再单列。
        for sid, rows in results:
            self.assertEqual(rows, {("name_cn", "cn", "哨兵碰撞名")},
                             f"哨兵 {sid}: 碰撞时中文行必须保留且唯一")

    def test_multilocale_names_are_searchable_via_normalize(self):
        """I-087: ja/ko/de 名称按 normalize_name 命中(搜索端不按语言过滤)。"""

        async def body():
            eng = _engine()
            try:
                async with eng.begin() as conn:
                    sid = await _alloc_sentinel_id(conn)
                cases = [
                    ("CB9101", "ja", "3-オキソブチルアミド哨兵"),
                    ("CB9102", "ko", "아세토아세트아미드哨兵"),
                    ("CB9103", "de", "Acetessigsäureamid Sentinel"),
                ]
                for cb_number, locale, name in cases:
                    async with eng.begin() as conn:
                        await upsert_externals_cb(conn, sid, cb_number, locale, name)
                    async with eng.begin() as conn:
                        row = (await conn.execute(text(
                            "SELECT count(*) FROM chemistry.name_index"
                            " WHERE chemical_id=:i AND kind='name_cn'"
                            "   AND normalized=:n AND source='cb'"
                        ), {"i": sid, "n": normalize_name(name)})).scalar()
                        if row != 1:
                            await _cleanup(eng, sid)
                            return name, row
                await _cleanup(eng, sid)
                return None, 1
            finally:
                await eng.dispose()

        async def upsert_externals_cb(conn, sid, cb_number, locale, name):
            from api.services.cb import upsert_externals
            await upsert_externals(
                conn, chemical_id=sid, cas_number="1000000-00-9",
                entry={"identity": {"cn": name}}, suppliers=[],
                status="ok", cb_number=cb_number, locale=locale)

        async def _cleanup(eng, sid):
            async with eng.begin() as conn:
                await conn.execute(text(
                    "DELETE FROM chemistry.chemical_cb WHERE chemical_id=:i"), {"i": sid})
                await conn.execute(text(
                    "DELETE FROM chemistry.chemicals WHERE id=:i"), {"i": sid})

        bad_name, count = self.run_coro(body())
        self.assertIsNone(bad_name)
        self.assertEqual(count, 1)

    def test_normalize_multilingual_examples(self):
        """归一化口径示例( receipts 依据): 仅小写化+空白折叠, 不做全半角/ß 折叠。"""
        cases = [
            ("  Acetessigsäureamid ", "acetessigsäureamid"),   # de 变音符保留
            ("STRASSE", "strasse"),                            # ASCII 大小写折叠
            ("Straße", "straße"),                              # ß 不折叠为 ss
            ("3-オキソブチルアミド", "3-オキソブチルアミド"),      # ja: 片假名长音不动
            ("３−オキソブチルアミド", "３−オキソブチルアミド"),     # ja: 全角数字不折半角
            ("아세토아세트아미드", "아세토아세트아미드"),          # ko: 谚文原样
            ("  多  空白  折叠  ", "多 空白 折叠"),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(normalize_name(raw), expected)

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
