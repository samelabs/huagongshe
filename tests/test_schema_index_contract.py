"""schema 契约: chemical_cb 必须有可服务 `chemical_id = $1` 的非部分索引 (0911)。

锁的契约(防回退):
  1. chemistry.chemical_cb 上存在至少一个 **非 partial**、**有效** 的索引
  2. 该索引的**首列**是 chemical_id
  3. 该索引真的能被规划器用来服务 FK / parent-delete / identity absorb 的定位谓词
     (enable_seqscan=off 下计划不得再出现 Seq Scan)

背景: 原有两个 chemical_id 前缀索引都是部分索引(WHERE cb_number IS NULL / NOT NULL),
裸谓词 `chemical_id = $1` 无法用它们 → RI CASCADE probe 退化成 1.27GB 并行顺序扫
(实测 544ms/行)。本测试保证该退化不会静默回潮。

运行: . /tmp/hgs_test_env.sh && ./venv/bin/python -m unittest tests.test_schema_index_contract -v
"""
from __future__ import annotations

import asyncio
import unittest

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

TABLE = "chemistry.chemical_cb"
COLUMN = "chemical_id"

# 结构性查询: 列出该表所有索引的首列 + 是否 partial + 是否 valid
INDEX_SQL = f"""
SELECT i.indexrelid::regclass::text                AS index_name,
       a.attname                                   AS first_col,
       (i.indpred IS NOT NULL)                     AS is_partial,
       i.indisvalid                                AS is_valid,
       pg_get_indexdef(i.indexrelid)               AS indexdef
  FROM pg_index i
  JOIN pg_class c   ON c.oid = i.indexrelid
  JOIN pg_namespace n ON n.oid = c.relnamespace
  JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = i.indkey[0]
 WHERE i.indrelid = '{TABLE}'::regclass
 ORDER BY 1
"""


def _engine():
    from tests.db_gate import ProductionDbBlocked, require_test_db
    try:
        url = require_test_db()
    except ProductionDbBlocked:
        raise unittest.SkipTest("需要测试库 (TEST_DATABASE_URL 过闸)")
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url.split("://", 1)[1]
    return create_async_engine(url.split("?", 1)[0], poolclass=NullPool)


class ChemicalCbFkIndexContract(unittest.TestCase):
    def test_non_partial_chemical_id_index_exists_and_serves_probe(self):
        asyncio.run(self._run())

    async def _run(self) -> None:
        engine = _engine()
        try:
            async with engine.connect() as conn:
                rows = (await conn.execute(text(INDEX_SQL))).mappings().fetchall()
                self.assertTrue(rows, f"{TABLE} 上找不到任何索引")

                usable = [r for r in rows
                          if r["first_col"] == COLUMN and not r["is_partial"] and r["is_valid"]]
                self.assertTrue(
                    usable,
                    "缺少可服务 chemical_id 的非部分有效索引 (现有: "
                    + "; ".join(f"{r['index_name']}[first={r['first_col']},"
                                f"partial={r['is_partial']},valid={r['is_valid']}]" for r in rows)
                    + ")")

                # 计划层验证: 关掉顺序扫后, 定位谓词必须走索引(不得再出现 Seq Scan)
                await conn.execute(text("SET enable_seqscan = off"))
                probe = (await conn.execute(text(
                    f"EXPLAIN SELECT 1 FROM {TABLE} WHERE {COLUMN} = -1 LIMIT 1"))).fetchall()
                plan = "\n".join(str(r[0]) for r in probe)
                self.assertNotIn("Seq Scan", plan,
                                 f"定位谓词仍在顺序扫, 计划:\n{plan}")
                self.assertTrue(
                    any(k in plan for k in ("Index Scan", "Index Only Scan", "Bitmap Index Scan")),
                    f"定位谓词未走索引, 计划:\n{plan}")
        finally:
            await engine.dispose()


class ChemicalCbFetchedAtIndexContract(unittest.TestCase):
    """契约: chemical_cb 必须有可服务 `ORDER BY fetched_at DESC NULLS LAST` 的索引。

    锁的是 /admin/pipeline latest-10 的计划形态 (0911, 实测 before = Parallel Seq Scan 1156.7ms)。
    indoption 位: 1 = DESC, 2 = NULLS FIRST —— 故 DESC NULLS LAST ⇒ indoption[0] & 1 = 1 且 & 2 = 0。
    """

    COLUMN = "fetched_at"

    SQL = f"""
    SELECT i.indexrelid::regclass::text          AS index_name,
           a.attname                             AS first_col,
           (i.indpred IS NOT NULL)               AS is_partial,
           i.indisvalid                          AS is_valid,
           i.indoption[0]                        AS indoption0,
           (i.indoption[0] & 1) = 1              AS is_desc,
           (i.indoption[0] & 2) = 0              AS is_nulls_last,
           pg_get_indexdef(i.indexrelid)         AS indexdef
      FROM pg_index i
      JOIN pg_class c     ON c.oid = i.indexrelid
      JOIN pg_namespace n ON n.oid = c.relnamespace
      JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = i.indkey[0]
     WHERE i.indrelid = '{TABLE}'::regclass
     ORDER BY 1
    """

    def test_fetched_at_index_serves_desc_nulls_last(self):
        asyncio.run(self._run())

    async def _run(self) -> None:
        engine = _engine()
        try:
            async with engine.connect() as conn:
                rows = (await conn.execute(text(self.SQL))).mappings().fetchall()
                self.assertTrue(rows, f"{TABLE} 上找不到任何索引")

                usable = [r for r in rows if r["first_col"] == self.COLUMN
                          and not r["is_partial"] and r["is_valid"]
                          and r["is_desc"] and r["is_nulls_last"]]
                self.assertTrue(
                    usable,
                    "缺少可服务 fetched_at DESC NULLS LAST 的有效非部分索引 (现有: "
                    + "; ".join(f"{r['index_name']}[first={r['first_col']},"
                                f"partial={r['is_partial']},valid={r['is_valid']},"
                                f"desc={r['is_desc']},nulls_last={r['is_nulls_last']}]" for r in rows)
                    + ")")

                # 计划层: latest-10 语义不得再出现 Seq Scan, 也不应再需要显式 Sort
                await conn.execute(text("SET enable_seqscan = off"))
                plan = "\n".join(str(r[0]) for r in (await conn.execute(text(
                    f"EXPLAIN SELECT chemical_id, locale, last_status, fetched_at "
                    f"FROM {TABLE} ORDER BY {self.COLUMN} DESC NULLS LAST LIMIT 10"))).fetchall())
                self.assertNotIn("Seq Scan", plan, f"latest-10 仍在顺序扫, 计划:\n{plan}")
                self.assertIn("idx_chemical_cb_fetched_at", plan, f"未使用目标索引, 计划:\n{plan}")
                self.assertNotIn("Sort", plan, f"仍在显式排序(索引未提供顺序), 计划:\n{plan}")
        finally:
            await engine.dispose()


if __name__ == "__main__":
    unittest.main()
