"""schema 契约: /api/admin/pipeline 统计查询的物理访问路径必须存在 (0918, E2-B)。

锁的契约(防回退):
  1. chemistry.chemical_cb 上存在**非 partial**、**有效**的
     (locale, fetched_at DESC NULLS LAST) B-tree `idx_chemical_cb_locale_fetched_at`
     —— 服务 `_scan_critical` 的 CB per-locale exact today/total/last_1h (admin.py:530);
  2. chemistry.chemical_pubchem 上存在**非 partial**、**有效**的
     (fetched_at DESC NULLS LAST) B-tree `idx_chemical_pubchem_fetched_at`
     —— 服务 Q2 exact 三计数 (admin.py:538) 与 latest_pb 的
     `ORDER BY fetched_at DESC NULLS LAST LIMIT 10` (admin.py:788);
  3. 计划层(enable_seqscan=off, 只锁"有可用访问路径", 不锁 planner 冷热选择):
     locale / fetched_at 定位谓词不得再落到 Seq Scan;
     latest_pb 必须是 index-driven 且**不再出现 Sort**;
  4. 两个 forward migration 文件存在且命名合法, 文件内**不含 CONCURRENTLY**
     (runner 以 psql --single-transaction 执行, CONCURRENTLY 不能在事务块内)
     也不含事务控制;
  5. migrations/0000_baseline.sql **未被修改**(sha256 冻结)。

背景: 0918 production 500 的根因是缺物理访问路径 —— chemical_cb 的 per-locale
三计数无 (locale, fetched_at) 覆盖, 必须整堆扫 3,562 MB(实测 heap 命中率 30.7%,
每次约 2.4 GB 落盘); chemical_pubchem 无任何 fetched_at 索引 → latest_pb 整堆扫
+ top-N Sort。索引**不改变** exact 计数语义 / LKG stale 语义 / optional 降级 /
response shape / statement_timeout。

注意(不夸大): 索引存在 ≠ index-only 一定被选中 —— Q1/Q2 的总量计数是否走
index-only 还取决于索引可见性(VM)位, 需 VACUUM 后由 planner 决定。本测试只锁
"物理访问路径存在且可被 planner 使用", 规模态计划证据见 E2-B 报告的 before/after
基准(test/benchmark DB 生产规模合成表)。

运行: . /tmp/hgs_test_env.sh && ./venv/bin/python -m unittest tests.test_pipeline_index_contract -v
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import re
import unittest

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CB_TABLE = "chemistry.chemical_cb"
PB_TABLE = "chemistry.chemical_pubchem"
CB_INDEX = "idx_chemical_cb_locale_fetched_at"
PB_INDEX = "idx_chemical_pubchem_fetched_at"

CB_MIGRATION = "20260918_01_index_chemical_cb_locale_fetched_at.sql"
PB_MIGRATION = "20260918_02_index_chemical_pubchem_fetched_at.sql"

# migrations/0000_baseline.sql 冻结哈希(2026-09-10 cutover baseline, 不可修改)
BASELINE_SHA256 = "ef808b8d83bba41270af742c2db005897002b8545ada64b64ed73fe22bbbd74a"
BASELINE_BYTES = 204742

INDEX_SQL = """
SELECT c.relname                                  AS index_name,
       pg_get_indexdef(i.indexrelid)              AS indexdef,
       (i.indpred IS NOT NULL)                    AS is_partial,
       i.indisvalid                               AS is_valid,
       i.indisready                               AS is_ready,
       i.indoption                                AS indoption,
       (SELECT array_agg(a.attname ORDER BY k.ord)
          FROM unnest(i.indkey) WITH ORDINALITY k(attnum, ord)
          JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.attnum
         WHERE k.ord <= 3)                        AS first_cols
  FROM pg_index i
  JOIN pg_class c ON c.oid = i.indexrelid
 WHERE i.indrelid = to_regclass(:tbl)
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


class PipelineIndexContract(unittest.TestCase):
    """两个索引的结构契约 + 计划层可用性(需要测试库)。"""

    def test_indexes_exist_with_exact_shape(self):
        asyncio.run(self._run_shape())

    def test_planner_has_index_access_paths(self):
        asyncio.run(self._run_plans())

    async def _run_shape(self) -> None:
        engine = _engine()
        try:
            async with engine.connect() as conn:
                cb = {r["index_name"]: dict(r) for r in (await conn.execute(
                    text(INDEX_SQL), {"tbl": CB_TABLE})).mappings().fetchall()}
                pb = {r["index_name"]: dict(r) for r in (await conn.execute(
                    text(INDEX_SQL), {"tbl": PB_TABLE})).mappings().fetchall()}

            problems: list[str] = []
            idx = cb.get(CB_INDEX)
            if idx is None:
                problems.append(f"{CB_TABLE} 缺 {CB_INDEX} (现有: {sorted(cb)})")
            else:
                if not idx["is_valid"]:
                    problems.append(f"{CB_INDEX} indisvalid=false")
                if not idx["is_ready"]:
                    problems.append(f"{CB_INDEX} indisready=false")
                if idx["is_partial"]:
                    problems.append(f"{CB_INDEX} 是 partial 索引(期望非 partial)")
                if tuple((idx["first_cols"] or [])[:2]) != ("locale", "fetched_at"):
                    problems.append(
                        f"{CB_INDEX} 前两列 {idx['first_cols']} (期望 ['locale','fetched_at'])")
                if "USING btree" not in idx["indexdef"]:
                    problems.append(f"{CB_INDEX} 不是 btree: {idx['indexdef']}")
                # 列序/方向: locale ASC NULLS LAST(0) + fetched_at DESC NULLS LAST(bit1=1,bit2=0)
                opt = list(idx["indoption"] or [])
                if len(opt) < 2:
                    problems.append(f"{CB_INDEX} indoption 异常: {opt}")
                else:
                    if opt[0] != 0:
                        problems.append(f"{CB_INDEX} locale 排序非 ASC NULLS LAST: {opt[0]}")
                    if (opt[1] & 1) != 1 or (opt[1] & 2) != 0:
                        problems.append(
                            f"{CB_INDEX} fetched_at 非 DESC NULLS LAST: indoption={opt[1]}")
                if "fetched_at DESC NULLS LAST" not in idx["indexdef"]:
                    problems.append(f"{CB_INDEX} indexdef 无 DESC NULLS LAST: {idx['indexdef']}")

            idx = pb.get(PB_INDEX)
            if idx is None:
                problems.append(f"{PB_TABLE} 缺 {PB_INDEX} (现有: {sorted(pb)})")
            else:
                if not idx["is_valid"]:
                    problems.append(f"{PB_INDEX} indisvalid=false")
                if not idx["is_ready"]:
                    problems.append(f"{PB_INDEX} indisready=false")
                if idx["is_partial"]:
                    problems.append(f"{PB_INDEX} 是 partial 索引(期望非 partial)")
                if tuple((idx["first_cols"] or [])[:1]) != ("fetched_at",):
                    problems.append(
                        f"{PB_INDEX} 首列 {idx['first_cols']} (期望 ['fetched_at'])")
                if "USING btree" not in idx["indexdef"]:
                    problems.append(f"{PB_INDEX} 不是 btree: {idx['indexdef']}")
                opt = list(idx["indoption"] or [])
                if not opt or (opt[0] & 1) != 1 or (opt[0] & 2) != 0:
                    problems.append(
                        f"{PB_INDEX} fetched_at 非 DESC NULLS LAST: indoption={opt}")
                if "fetched_at DESC NULLS LAST" not in idx["indexdef"]:
                    problems.append(f"{PB_INDEX} indexdef 无 DESC NULLS LAST: {idx['indexdef']}")

            self.assertEqual(problems, [],
                             "pipeline 统计索引契约被破坏: " + "; ".join(problems))
        finally:
            await engine.dispose()

    async def _run_plans(self) -> None:
        engine = _engine()
        try:
            async with engine.connect() as conn:
                # 只锁"存在可用访问路径": 关掉顺序扫, 避免小表/冷热差异造成假红
                await conn.execute(text("SET enable_seqscan = off"))

                q1 = "\n".join(str(r[0]) for r in (await conn.execute(text(
                    "EXPLAIN SELECT locale, count(*) FROM chemistry.chemical_cb "
                    "WHERE locale = 'zh-CN' GROUP BY locale"))).fetchall())
                self.assertNotIn("Seq Scan", q1, f"Q1 定位谓词仍顺序扫:\n{q1}")
                self.assertIn(CB_INDEX, q1, f"Q1 未走目标索引:\n{q1}")

                q2 = "\n".join(str(r[0]) for r in (await conn.execute(text(
                    "EXPLAIN SELECT count(*) FROM chemistry.chemical_pubchem "
                    "WHERE fetched_at >= current_date"))).fetchall())
                self.assertNotIn("Seq Scan", q2, f"Q2 时间窗谓词仍顺序扫:\n{q2}")
                self.assertIn(PB_INDEX, q2, f"Q2 未走目标索引:\n{q2}")

                r2 = "\n".join(str(r[0]) for r in (await conn.execute(text(
                    "EXPLAIN SELECT p.chemical_id, p.record_title, c.pubchem_cid, "
                    "c.preferred_name, p.fetched_at "
                    "FROM chemistry.chemical_pubchem p "
                    "LEFT JOIN chemistry.chemicals c ON c.id = p.chemical_id "
                    "ORDER BY p.fetched_at DESC NULLS LAST LIMIT 10"))).fetchall())
                self.assertNotIn("Seq Scan", r2, f"R2 仍顺序扫:\n{r2}")
                self.assertIn(PB_INDEX, r2, f"R2 未走目标索引:\n{r2}")
                self.assertNotIn("Sort", r2, f"R2 仍在显式排序(索引未提供顺序):\n{r2}")
        finally:
            await engine.dispose()


class PipelineMigrationContract(unittest.TestCase):
    """forward migration 文本契约(不需要测试库)。"""

    EXPECTED = {
        CB_MIGRATION: (
            "CREATE INDEX IF NOT EXISTS idx_chemical_cb_locale_fetched_at\n"
            "    ON chemistry.chemical_cb (locale, fetched_at DESC NULLS LAST);"),
        PB_MIGRATION: (
            "CREATE INDEX IF NOT EXISTS idx_chemical_pubchem_fetched_at\n"
            "    ON chemistry.chemical_pubchem (fetched_at DESC NULLS LAST);"),
    }

    def _path(self, name: str) -> str:
        return os.path.join(ROOT, "migrations", name)

    def test_forward_migrations_present_and_ordered(self):
        from scripts.migrate import FORWARD_RE
        fwd = sorted(f for f in os.listdir(os.path.join(ROOT, "migrations"))
                     if FORWARD_RE.match(f))
        for name in self.EXPECTED:
            self.assertIn(name, fwd, f"{name} 不在 forward 集合: {fwd}")
        self.assertLess(fwd.index(CB_MIGRATION), fwd.index(PB_MIGRATION),
                        "chemical_cb 索引 migration 必须先于 pubchem")

    def test_migration_files_are_single_statement_and_no_concurrently(self):
        for name, stmt in self.EXPECTED.items():
            with open(self._path(name), encoding="utf-8") as fh:
                sql = fh.read()
            # 只判可执行语句: 去掉 `--` 行注释(注释里会解释"为何不用 CONCURRENTLY")
            code = "\n".join(ln.split("--", 1)[0] for ln in sql.splitlines())
            # 只做一件事: 恰一条 CREATE INDEX
            self.assertEqual(
                len(re.findall(r"(?im)^\s*CREATE\s+INDEX", code)), 1,
                f"{name} 不是单一 CREATE INDEX 职责")
            self.assertIn(stmt, code, f"{name} 索引定义与契约不符")
            # CONCURRENTLY 不能在 runner 的 --single-transaction 内执行
            self.assertNotIn("CONCURRENTLY", code.upper(),
                             f"{name} 含 CONCURRENTLY(runner 单事务内不可执行)")
            # runner owns transaction: 顶层不得含事务控制
            for line in code.splitlines():
                stripped = line.strip().rstrip(";").strip().upper()
                self.assertNotIn(stripped, {"BEGIN", "COMMIT", "ROLLBACK"},
                                 f"transaction control in {name}: {line!r}")
            # 幂等形式: 不允许裸 CREATE INDEX(无 IF NOT EXISTS)
            self.assertEqual(
                len(re.findall(r"(?i)CREATE\s+INDEX\s+IF\s+NOT\s+EXISTS", code)),
                len(re.findall(r"(?im)^\s*CREATE\s+INDEX", code)),
                f"{name} 存在非幂等 CREATE INDEX")

    def test_baseline_sql_not_modified(self):
        with open(self._path("0000_baseline.sql"), "rb") as fh:
            raw = fh.read()
        self.assertEqual(len(raw), BASELINE_BYTES,
                         "migrations/0000_baseline.sql 字节数变化(冻结文件不得修改)")
        self.assertEqual(hashlib.sha256(raw).hexdigest(), BASELINE_SHA256,
                         "migrations/0000_baseline.sql 内容变化(冻结文件不得修改)")

    def test_baseline_does_not_carry_pipeline_indexes(self):
        """两个索引只经 forward migration 引入, baseline 不承载。"""
        with open(self._path("0000_baseline.sql"), encoding="utf-8") as fh:
            baseline = fh.read()
        for name in (CB_INDEX, PB_INDEX):
            self.assertNotIn(name, baseline,
                             f"baseline 不应包含 {name}(本轮变更只走 forward migration)")


if __name__ == "__main__":
    unittest.main()
