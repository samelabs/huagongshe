# 0907 lease cb 键域专项: request_context.source_cb 必须按 jobId 取, 不得回落错主表
# 背景: cb_map 键域混用(jobId 写入 / chemicalId lookup)致 source_cb 永远失效,
# targeted canary 跨 cb 串抓事故。本测试直打测试 DB + claim SQL (0909 起必须过测试库闸)。
import asyncio
import os
import re
import unittest

DB_URL = None
try:
    from tests.db_gate import test_db_or_skip
    _raw = test_db_or_skip()
except Exception:
    _raw = None
if _raw:
    DB_URL = _raw
    DB_URL = _raw.split("?")[0]  # 去 sentinel query, 不下传驱动
    ASYNC = re.sub(r'postgres(?:ql)?://([^:]+):([^@]+)@',
                   lambda m: f'postgresql+asyncpg://{m.group(1)}:{m.group(2)}@',
                   DB_URL)

P = "UT2-LCB-"
CAS_A = "99999-77-7"


_LOOP = asyncio.new_event_loop()


def _run(coro):
    return _LOOP.run_until_complete(coro)


@unittest.skipUnless(DB_URL, "需要测试库 (TEST_DATABASE_URL 过闸)")
class LeaseCbKeyDomainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy import text

        async def setup():
            cls.engine = create_async_engine(ASYNC)
            async with cls.engine.begin() as db:
                await db.execute(text(
                    "DELETE FROM maintenance.cas_jobs"
                    " WHERE request_context->>'source_cb' LIKE :p"
                    " OR cas_number=:c"), {"p": P + '%', "c": CAS_A})
                await db.execute(text(
                    "DELETE FROM chemistry.chemical_cb WHERE cb_number LIKE :p"),
                    {"p": P + '%'})
                await db.execute(text(
                    "DELETE FROM chemistry.chemicals WHERE cas_numbers && ARRAY[:c]::text[]"),
                    {"c": CAS_A})
        _run(setup())

    @classmethod
    def tearDownClass(cls):
        from sqlalchemy import text

        async def teardown():
            async with cls.engine.begin() as db:
                await db.execute(text(
                    "DELETE FROM maintenance.cas_jobs"
                    " WHERE request_context->>'source_cb' LIKE :p"
                    " OR cas_number=:c"), {"p": P + '%', "c": CAS_A})
                await db.execute(text(
                    "DELETE FROM chemistry.chemical_cb WHERE cb_number LIKE :p"),
                    {"p": P + '%'})
                await db.execute(text(
                    "DELETE FROM chemistry.chemicals WHERE cas_numbers && ARRAY[:c]::text[]"),
                    {"c": CAS_A})
            await cls.engine.dispose()
        _run(teardown())

    def _insert_chem(self, cb=None):
        from sqlalchemy import text

        async def go():
            async with self.engine.begin() as db:
                cid = (await db.execute(text(
                    "INSERT INTO chemistry.chemicals (cas_numbers, cb_number)"
                    " VALUES (ARRAY[:c]::text[], :cb) RETURNING id"),
                    {"c": CAS_A, "cb": cb})).scalar()
                return cid
        return _run(go())

    def _insert_job(self, cid, source_cb=None, priority=99):
        # priority=99: 测试 job 必须压过生产 backfill 队列(priority 20/50),
        # 否则 lease ORDER BY priority DESC 先派发生产行, 测试 job 永不入列。
        from sqlalchemy import text

        async def go():
            async with self.engine.begin() as db:
                ctx = ("SELECT jsonb_build_object("
                       "'source_cb', CAST(:scb AS text))"
                       if source_cb else "SELECT '{}'::jsonb")
                jid = (await db.execute(text(
                    "INSERT INTO maintenance.cas_jobs"
                    " (chemical_id, cas_number, dedupe_key, priority,"
                    "  status, request_context)"
                    " VALUES (:cid, :cas, :dk, :prio, 'queued',"
                    f"  ({ctx}))"
                    " RETURNING id"),
                    {"cid": cid, "cas": CAS_A, "dk": f"{P}{source_cb or 'nocb'}-{cid}",
                     "prio": priority, "scb": source_cb})).scalar()
                return jid
        return _run(go())

    def _claim(self):
        """调真实 workapi.cas_lease_jobs — 与生产 lease 路径完全一致"""
        from types import SimpleNamespace
        from api.workapi import cas_lease_jobs
        body = SimpleNamespace(max_jobs=10, capabilities=["cas"])
        worker = SimpleNamespace(worker_id="ut2-lease", max_lease_jobs=10)

        async def go():
            async with self.engine.connect() as db:
                return await cas_lease_jobs(body=body, db=db, worker=worker)
        return _run(go())

    def _finish(self, jid):
        from sqlalchemy import text

        async def go():
            async with self.engine.begin() as db:
                await db.execute(text(
                    "DELETE FROM maintenance.cas_jobs WHERE id=:i"), {"i": jid})
        _run(go())

    def test_a1_same_chem_two_cb_two_jobs(self):
        # A1: same chemical/CAS, source_cb=CB001/CB002 — 各自 lease 各自 cb
        cid = self._insert_chem(cb=P + "CBX")  # 主表放第三个 cb 更严
        j1 = self._insert_job(cid, source_cb=P + "CB001")
        j2 = self._insert_job(cid, source_cb=P + "CB002")
        got = {}
        for _ in range(2):
            res = self._claim()
            for j in res["jobs"]:
                if j["job_id"] in (j1, j2):
                    got[j["job_id"]] = j["cb_number"]
        self.assertEqual(got.get(j1), P + "CB001",
                         f"job1 应取自己的 source_cb, got {got.get(j1)}")
        self.assertEqual(got.get(j2), P + "CB002",
                         f"job2 应取自己的 source_cb, got {got.get(j2)}")
        self._finish(j1); self._finish(j2)

    def test_a2_context_beats_main_table(self):
        # A2: 主表 CB999, job source_cb=CB001 → 必须 CB001
        cid = self._insert_chem(cb=P + "CB999")
        j = self._insert_job(cid, source_cb=P + "CB001")
        res = self._claim()
        row = next((x for x in res["jobs"] if x["job_id"] == j), None)
        self.assertIsNotNone(row)
        self.assertEqual(row["cb_number"], P + "CB001")
        self._finish(j)

    def test_a3_null_main_exact_path(self):
        # A3: 主表 NULL + source_cb 有值 → lease 必须给出该 cb (path A 前提)
        cid = self._insert_chem(cb=None)
        j = self._insert_job(cid, source_cb=P + "CB001")
        res = self._claim()
        row = next((x for x in res["jobs"] if x["job_id"] == j), None)
        self.assertIsNotNone(row)
        self.assertEqual(row["cb_number"], P + "CB001",
                         "主表 NULL 不得吞掉 source_cb 走 generic path B")
        self._finish(j)

    def test_a4_legacy_no_context_fallback(self):
        # A4: 无 source_cb 的 legacy job → 主表 CB999 fallback, 线上零漂移
        cid = self._insert_chem(cb=P + "CB999")
        j = self._insert_job(cid, source_cb=None)
        res = self._claim()
        row = next((x for x in res["jobs"] if x["job_id"] == j), None)
        self.assertIsNotNone(row)
        self.assertEqual(row["cb_number"], P + "CB999")
        self._finish(j)


if __name__ == "__main__":
    unittest.main()
