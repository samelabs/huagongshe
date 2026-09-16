"""schema 契约: 名称搜索 exact B-tree 三件套必须存在 (0916 三阶段生产索引修复)。

锁的契约(防回退): baseline / migration 整理不得把 exact 搜索物理索引误删,
也不得顺手删掉 fuzzy 用的 trigram GIN —— 两者服务于 run_name_search 的
不同路径(exact 等值 vs fuzzy substring), 缺一即回退到 0916 修复前的
trgm 假阳性回表(生产实测 benzene 三路 952/991/410ms, 冷态 5-6s 撞
statement_timeout → /api/search 503)。

锁定内容:
  1. chemistry.chemicals 上存在 (preferred_name, id) partial B-tree
     (WHERE preferred_name IS NOT NULL), valid;
  2. chemistry.chemicals 上存在 (iupac_name, id) partial B-tree
     (WHERE iupac_name IS NOT NULL), valid;
  3. chemistry.name_index 上存在非部分 (normalized, chemical_id) B-tree, valid;
  4. 三个 trgm fuzzy GIN (preferred/iupac/normalized) 仍存在且 valid。

运行: . /tmp/hgs_test_env.sh && ./venv/bin/python -m unittest tests.test_search_exact_index_contract -v
"""
from __future__ import annotations

import asyncio
import unittest

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

# (表, 索引名, 列对, 是否期望 partial)
EXACT_BTREES = [
    ("chemistry.chemicals", "chemicals_preferred_name_exact_idx",
     ("preferred_name", "id"), True),
    ("chemistry.chemicals", "chemicals_iupac_name_exact_idx",
     ("iupac_name", "id"), True),
    ("chemistry.name_index", "name_index_normalized_exact_idx",
     ("normalized", "chemical_id"), False),
]

# fuzzy trigram GIN 三件套(baseline 建于各表, 不得被误删)
TRGM_GINS = [
    ("chemistry.chemicals", "chemicals_preferred_name_trgm_idx"),
    ("chemistry.chemicals", "chemicals_iupac_name_trgm_idx"),
    ("chemistry.name_index", "name_index_normalized_trgm_idx"),
]


def _engine():
    from tests.db_gate import ProductionDbBlocked, require_test_db
    try:
        url = require_test_db()
    except ProductionDbBlocked:
        raise unittest.SkipTest("需要测试库 (TEST_DATABASE_URL 过闸)")
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url.split("://", 1)[1]
    return create_async_engine(url.split("?", 1)[0], poolclass=NullPool)


def _index_sql(table: str) -> str:
    return f"""
SELECT c.relname                                AS index_name,
       pg_get_indexdef(i.indexrelid)            AS indexdef,
       (i.indpred IS NOT NULL)                  AS is_partial,
       i.indisvalid                             AS is_valid,
       (SELECT array_agg(a.attname ORDER BY k.ord)
          FROM unnest(i.indkey) WITH ORDINALITY k(attnum, ord)
          JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.attnum
         WHERE k.ord <= 2)                      AS first_two_cols
  FROM pg_index i
  JOIN pg_class c ON c.oid = i.indexrelid
 WHERE i.indrelid = '{table}'::regclass
"""


class SearchExactIndexContract(unittest.TestCase):
    def test_three_exact_btrees_and_trgm_gins_exist(self):
        asyncio.run(self._run())

    async def _run(self) -> None:
        engine = _engine()
        try:
            tables = {t for t, *_ in EXACT_BTREES} | {t for t, _ in TRGM_GINS}
            indexes: dict[str, dict[str, dict]] = {}
            async with engine.connect() as conn:
                for table in tables:
                    rows = (await conn.execute(
                        text(_index_sql(table)))).mappings().fetchall()
                    indexes[table] = {r["index_name"]: dict(r) for r in rows}

            problems: list[str] = []
            for table, name, cols, expect_partial in EXACT_BTREES:
                idx = indexes.get(table, {}).get(name)
                if idx is None:
                    problems.append(f"{table} 缺 {name}")
                    continue
                if not idx["is_valid"]:
                    problems.append(f"{name} 存在但 indisvalid=false")
                if idx["is_partial"] != expect_partial:
                    problems.append(
                        f"{name} partial={idx['is_partial']} (期望 {expect_partial})")
                got_cols = idx["first_two_cols"] or []
                if tuple(got_cols[:2]) != cols:
                    problems.append(
                        f"{name} 前两列 {got_cols} (期望 {list(cols)})")
                if "USING btree" not in idx["indexdef"]:
                    problems.append(f"{name} 不是 btree: {idx['indexdef']}")
                if expect_partial and "IS NOT NULL" not in idx["indexdef"]:
                    problems.append(f"{name} 缺 partial 谓词: {idx['indexdef']}")

            for table, name in TRGM_GINS:
                idx = indexes.get(table, {}).get(name)
                if idx is None:
                    problems.append(f"{table} 缺 fuzzy trgm GIN {name}")
                    continue
                if not idx["is_valid"]:
                    problems.append(f"{name} 存在但 indisvalid=false")
                if "gin" not in idx["indexdef"].lower():
                    problems.append(f"{name} 不是 GIN: {idx['indexdef']}")

            self.assertEqual(
                problems, [],
                "名称搜索索引契约被破坏: " + "; ".join(problems))
        finally:
            await engine.dispose()


if __name__ == "__main__":
    unittest.main()
