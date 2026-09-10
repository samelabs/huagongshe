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


if __name__ == "__main__":
    unittest.main()
