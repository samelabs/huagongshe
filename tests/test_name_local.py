"""/ — 多语言名称针对性测试。

覆盖:
1. name_local 契约: enrich 载荷里按请求 locale 附该语言 CB 当地名
   (fetch_chemicals 是 detail 与 search 共用的组装点);
   zh-CN 时 name_local 与 name_cn 一致; 多条 ok 行按 cb_number 取第一条;
   locale 缺省/白名单外 → null; 该 locale 无 ok 行 → null。
2. 零 provider 访问: attach 只读 chemistry.chemical_cb 一张表。

真链测试库 + 一次性哨兵行(与 test_name_index 同法), 生产数据零接触。
"""
from __future__ import annotations

import json
import unittest

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from api.services.chemicals import CHEMICAL_SELECT, fetch_chemicals

SETUP_SQL = """
INSERT INTO chemistry.chemicals
  (id, smiles, molecular_formula, average_mass, monoisotopic_mass,
   inchikey, mol, morgan_bfp, morgan_sfp, preferred_name, iupac_name,
   created_at, updated_at)
VALUES
  (:id, 'CCO', 'C2H6O', 46.07, 46.0419, 'LFQSCWFLJHTTHZ-UHFFFAOYSA-N',
   mol_from_smiles('CCO'), morganbv_fp(mol_from_smiles('CCO')),
   morgan_fp(mol_from_smiles('CCO')),
   '哨兵乙醇-local', 'ethanol-local-test', now(), now())
ON CONFLICT (id) DO UPDATE SET preferred_name='哨兵乙醇-local',
  iupac_name='ethanol-local-test'
"""


def _engine():
    from tests.db_gate import require_test_db, ProductionDbBlocked
    try:
        url = require_test_db()
    except ProductionDbBlocked:
        raise unittest.SkipTest("需要测试库 (TEST_DATABASE_URL 过闸)")
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url.split("://", 1)[1]
    return create_async_engine(url.split("?", 1)[0])


def _cb_rows(sid: int) -> list[tuple[str, str, str]]:
    """(cb_number, locale, 当地名): ja 两条(验 cb_number 取第一)、ko/de/zh 各一。"""
    return [
        ("CB9202", "ja", "3-オキソブチルアミド哨兵"),
        ("CB9201", "ja", "アセトアセトアミド哨兵"),
        ("CB9203", "ko", "아세토아세트아미드哨兵"),
        ("CB9204", "de", "Acetessigsäureamid-Sentinel"),
        ("CB9200", "zh-CN", "哨兵乙酰乙酰胺"),
    ]


class NameLocalTests(unittest.TestCase):
    def _run(self, coro):
        import asyncio
        return asyncio.run(coro)

    def test_name_local_contract(self):
        async def body():
            eng = _engine()
            try:
                async with eng.begin() as conn:
                    row = (await conn.execute(text(
                        "SELECT greatest(coalesce(max(id),0), 100000000) + 1"
                        " FROM chemistry.chemicals"))).scalar()
                    sid = int(row)
                    await conn.execute(text(
                        "DELETE FROM chemistry.name_index WHERE chemical_id=:i"),
                        {"i": sid})
                    await conn.execute(text(
                        "DELETE FROM chemistry.chemical_cb WHERE chemical_id=:i"),
                        {"i": sid})
                    await conn.execute(text(SETUP_SQL), {"id": sid})
                    for cb_number, locale, cn in _cb_rows(sid):
                        await conn.execute(text("""
                            INSERT INTO chemistry.chemical_cb
                              (chemical_id,cas_number,cb_number,entry,
                               last_status,fetched_at,locale)
                            VALUES (:i,'1000000-01-9',:cb,
                                    CAST(:entry AS jsonb),'ok',now(),:locale)
                        """), {
                            "i": sid, "cb": cb_number, "locale": locale,
                            "entry": json.dumps({"identity": {"cn": cn}}),
                        })
                    # name_cn 由 attach_localized_names 填充(镜像 name_index)
                    await conn.execute(text("""
                        INSERT INTO chemistry.name_index
                          (chemical_id,name,lang,normalized,source,kind)
                        VALUES (:i,'哨兵乙酰乙酰胺','cn','哨兵乙酰乙酰胺','cb','name_cn')
                        ON CONFLICT DO NOTHING
                    """), {"i": sid})

                    results = {}
                    for locale in ("ja", "ko", "de", "zh-CN", "en", None, "fr"):
                        items = await fetch_chemicals(conn, f"""
                            SELECT {CHEMICAL_SELECT}
                            FROM chemistry.chemicals c WHERE c.id=:id
                        """, {"id": sid}, locale=locale)
                        results[locale] = (items[0]["name_cn"],
                                           items[0]["name_local"])

                    # 清理哨兵
                    await conn.execute(text(
                        "DELETE FROM chemistry.chemical_cb WHERE chemical_id=:i"),
                        {"i": sid})
                    await conn.execute(text(
                        "DELETE FROM chemistry.name_index WHERE chemical_id=:i"),
                        {"i": sid})
                    await conn.execute(text(
                        "DELETE FROM chemistry.chemicals WHERE id=:i"), {"i": sid})
                    return results
            finally:
                await eng.dispose()

        r = self._run(body())
        # 各语言当地名(ja 两条 ok 行: CB9201 < CB9202 → 取 CB9201 的名字)
        self.assertEqual(r["ja"], ("哨兵乙酰乙酰胺", "アセトアセトアミド哨兵"))
        self.assertEqual(r["ko"], ("哨兵乙酰乙酰胺", "아세토아세트아미드哨兵"))
        self.assertEqual(r["de"], ("哨兵乙酰乙酰胺", "Acetessigsäureamid-Sentinel"))
        # zh-CN: name_local 与 name_cn 一致(工单契约)
        self.assertEqual(r["zh-CN"], ("哨兵乙酰乙酰胺", "哨兵乙酰乙酰胺"))
        # en 无 ok 行 → null; 缺省/白名单外 → null
        self.assertEqual(r["en"], ("哨兵乙酰乙酰胺", None))
        self.assertEqual(r[None], ("哨兵乙酰乙酰胺", None))
        self.assertEqual(r["fr"], ("哨兵乙酰乙酰胺", None))

    def test_ja_name_local_prefers_lowest_cb_number(self):
        """多条同 locale ok 行: name_local 取 cb_number 最小的一条。"""

        async def body():
            eng = _engine()
            try:
                async with eng.begin() as conn:
                    sid = int((await conn.execute(text(
                        "SELECT greatest(coalesce(max(id),0), 100000000) + 1"
                        " FROM chemistry.chemicals"))).scalar())
                    await conn.execute(text(
                        "DELETE FROM chemistry.chemical_cb WHERE chemical_id=:i"),
                        {"i": sid})
                    await conn.execute(text(SETUP_SQL), {"id": sid})
                    for cb_number, name in (("CB0099", "低号名哨兵"),
                                            ("CB0001", "最低号名哨兵")):
                        await conn.execute(text("""
                            INSERT INTO chemistry.chemical_cb
                              (chemical_id,cas_number,cb_number,entry,
                               last_status,fetched_at,locale)
                            VALUES (:i,'1000000-02-8',:cb,
                                    CAST(:entry AS jsonb),'ok',now(),'ja')
                        """), {
                            "i": sid, "cb": cb_number,
                            "entry": json.dumps({"identity": {"cn": name}}),
                        })
                    items = await fetch_chemicals(conn, f"""
                        SELECT {CHEMICAL_SELECT} FROM chemistry.chemicals c
                        WHERE c.id=:id
                    """, {"id": sid}, locale="ja")
                    local = items[0]["name_local"]
                    await conn.execute(text(
                        "DELETE FROM chemistry.chemical_cb WHERE chemical_id=:i"),
                        {"i": sid})
                    await conn.execute(text(
                        "DELETE FROM chemistry.chemicals WHERE id=:i"), {"i": sid})
                    return local
            finally:
                await eng.dispose()

        self.assertEqual(self._run(body()), "最低号名哨兵")


if __name__ == "__main__":
    unittest.main()
