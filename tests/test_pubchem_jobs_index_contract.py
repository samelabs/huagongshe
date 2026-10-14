"""v1.7.2 — pubchem_identity_jobs 领任务/租约回收索引契约（20261015_01）。

生产实测（约 25.6 万行, 全部终态）: worker 每次领任务都对全表顺序扫描 ——
过期租约回收(WHERE status='leased' AND lease_expires_at<=now())无可用索引;
claim 的 ORDER BY priority DESC, id 与旧 (status, priority, id) 索引方向
不一致, 需要 Incremental Sort 补序。

本文件锁（对齐 cas_jobs 已有的 cas_jobs_claim_idx/cas_jobs_lease_expiry_idx）:
1. 两个部分索引存在且形状精确（方向/谓词）;
2. 与 cas_jobs 同形（补齐一致性, 不再漂移）;
3. 索引 COMMENT 写明各自服务的查询;
4. 计划层: 两条真实查询有可用索引访问路径, 无 Seq Scan, claim 无 Sort。

直连测试库(test_hgs); 小表数据下用 enable_seqscan=off 锁"存在可用路径"
（同 tests/test_pipeline_index_contract 手法, 避免行数差异造成假红）。
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.db_gate import test_db_or_skip  # noqa: E402,F401

import os

DB_URL = os.environ.get("TEST_DATABASE_URL", "")
_GATE = unittest.skipUnless(DB_URL, "需要 PG 测试库")

TABLE = "maintenance.pubchem_identity_jobs"
CLAIM_IDX = "pubchem_identity_jobs_claim_idx"
LEASE_IDX = "pubchem_identity_jobs_lease_expiry_idx"

_INDEX_SQL = """
SELECT c.relname AS index_name, pg_get_indexdef(i.indexrelid) AS indexdef,
       i.indisvalid AS is_valid
  FROM pg_index i
  JOIN pg_class c ON c.oid = i.indexrelid
 WHERE i.indrelid = to_regclass(:tbl)
"""

# workapi_jobs.py 领任务路径的两条真实查询(EXPLAIN only, 不执行)
_RECLAIM_PLAN = """
EXPLAIN UPDATE maintenance.pubchem_identity_jobs
   SET status='queued',lease_owner=NULL,lease_token_hash=NULL,
       lease_expires_at=NULL,updated_at=now(),
       last_error_code='lease_expired'
 WHERE status='leased' AND lease_expires_at<=now()
"""

_CLAIM_PLAN = """
EXPLAIN SELECT j.id,j.chemical_id,j.evidence_value
  FROM maintenance.pubchem_identity_jobs j
 WHERE j.status='queued'
 ORDER BY j.priority DESC,j.id
 LIMIT 10 FOR UPDATE OF j SKIP LOCKED
"""


def _engine():
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool
    url = DB_URL.split("?")[0]
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url.split("://", 1)[1]
    return create_async_engine(url, poolclass=NullPool)


@_GATE
class PubchemJobsIndexContract(unittest.TestCase):
    def test_index_shapes_exact(self):
        """两个部分索引存在: claim (priority DESC, id) WHERE queued;
        lease (lease_expires_at, id) WHERE leased —— 与 cas_jobs 同形。"""
        from sqlalchemy import text

        async def go():
            engine = _engine()
            try:
                async with engine.connect() as c:
                    idx = {r["index_name"]: dict(r) for r in (await c.execute(
                        text(_INDEX_SQL), {"tbl": TABLE})).mappings().fetchall()}
                    cas = {r["index_name"]: dict(r) for r in (await c.execute(
                        text(_INDEX_SQL), {"tbl": "maintenance.cas_jobs"})).mappings().fetchall()}
                return idx, cas
            finally:
                await engine.dispose()

        idx, cas = asyncio.run(go())
        claim, lease = idx.get(CLAIM_IDX), idx.get(LEASE_IDX)
        self.assertIsNotNone(claim, f"缺 {CLAIM_IDX} (现有: {sorted(idx)})")
        self.assertIsNotNone(lease, f"缺 {LEASE_IDX} (现有: {sorted(idx)})")
        for i in (claim, lease):
            self.assertTrue(i["is_valid"])
            self.assertIn("WHERE", i["indexdef"])
        self.assertIn("(priority DESC, id)", claim["indexdef"])
        self.assertIn("status = 'queued'::text", claim["indexdef"])
        self.assertIn("(lease_expires_at, id)", lease["indexdef"])
        self.assertIn("status = 'leased'::text", lease["indexdef"])
        # 与 cas_jobs 同形: 归一化表名后 indexdef 一致
        norm = lambda d: d.replace("pubchem_identity_jobs", "J").replace(  # noqa: E731
            "cas_jobs", "J").replace("maintenance.J", "J")
        self.assertEqual(norm(claim["indexdef"]), norm(cas["cas_jobs_claim_idx"]["indexdef"]),
                         "claim 索引须与 cas_jobs_claim_idx 同形")
        self.assertEqual(norm(lease["indexdef"]), norm(cas["cas_jobs_lease_expiry_idx"]["indexdef"]),
                         "lease 索引须与 cas_jobs_lease_expiry_idx 同形")

    def test_index_comments_document_served_queries(self):
        """每个索引的 COMMENT 写明服务的查询（防止未来误删/误改）。"""
        from sqlalchemy import text

        async def go():
            engine = _engine()
            try:
                async with engine.connect() as c:
                    rows = (await c.execute(text("""
                        SELECT c.relname,
                               obj_description(i.indexrelid, 'pg_class') AS comment
                          FROM pg_index i
                          JOIN pg_class c ON c.oid = i.indexrelid
                         WHERE i.indrelid = to_regclass(:tbl)
                           AND c.relname IN (:a, :b)
                    """), {"tbl": TABLE, "a": CLAIM_IDX, "b": LEASE_IDX})).all()
                return dict(rows)
            finally:
                await engine.dispose()

        comments = asyncio.run(go())
        claim_c = comments.get(CLAIM_IDX) or ""
        lease_c = comments.get(LEASE_IDX) or ""
        self.assertIn("ORDER BY priority DESC", claim_c,
                      f"claim 索引注释须写明服务的领任务查询: {claim_c!r}")
        self.assertIn("lease_expires_at<=now()", lease_c,
                      f"lease 索引注释须写明服务的回收查询: {lease_c!r}")

    def test_plans_use_indexes_no_seqscan_no_claim_sort(self):
        """计划层: 回收与领任务都有索引访问路径; claim 排序由索引提供。"""
        from sqlalchemy import text

        async def go():
            engine = _engine()
            try:
                async with engine.connect() as c:
                    await c.execute(text("SET enable_seqscan = off"))
                    reclaim = "\n".join(str(r[0]) for r in (await c.execute(
                        text(_RECLAIM_PLAN))).fetchall())
                    claim = "\n".join(str(r[0]) for r in (await c.execute(
                        text(_CLAIM_PLAN))).fetchall())
                return reclaim, claim
            finally:
                await engine.dispose()

        reclaim, claim = asyncio.run(go())
        # 回收: 走 lease_expiry 索引, 不再全表扫
        self.assertNotIn("Seq Scan", reclaim, f"回收仍顺序扫:\n{reclaim}")
        self.assertIn(LEASE_IDX, reclaim, f"回收未走目标索引:\n{reclaim}")
        # 领任务: 走 claim 索引, 排序由索引提供(无 Sort 节点)
        self.assertNotIn("Seq Scan", claim, f"claim 仍顺序扫:\n{claim}")
        self.assertIn(CLAIM_IDX, claim, f"claim 未走目标索引:\n{claim}")
        self.assertNotIn("Sort", claim,
                         f"claim 仍需排序(索引方向与 ORDER BY 不一致):\n{claim}")


if __name__ == "__main__":
    unittest.main()
