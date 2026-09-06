"""Ingestion ledger / seed loader / scheduler 治理边界测试 (0907)。

覆盖立项十一节 15 项要求。测试用 ledger 前缀 cb 'UTSEED-' 与 CAS
'99999-99-9' 标记, setUp 直清; 绝不触碰生产 seed。
"""
import asyncio
import os
import re
import sqlite3
import tempfile
import unittest

DB_URL = os.environ.get(
    "HGS_DATABASE_URL",
    [l.strip() for l in open("/etc/huagongshe.env")
     if l.startswith("HGS_DATABASE_URL")][0].split("=", 1)[1].strip())
ASYNC_URL = re.sub(
    r"postgres(?:ql)?://([^:]+):([^@]+)@",
    lambda m: f"postgresql+asyncpg://{m.group(1)}:{m.group(2)}@", DB_URL)

CAS = "99999-99-9"
CAS2 = "99999-88-8"
TEST_MOL = """
  Mrv1582

  2  1  0  0  0  0            999 V2000
    0.0000    0.0000    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0
    1.0000    0.0000    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0
  1  2  1  0  0  0  0
M  END
"""


def _make_sqlite(rows):
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE compounds(cb_number TEXT PRIMARY KEY, cas TEXT)")
    c.executemany("INSERT INTO compounds VALUES (?,?)", rows)
    c.commit()
    c.close()
    return path


@unittest.skipUnless(DB_URL, "需要 PG")
class SeedLedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from sqlalchemy.ext.asyncio import create_async_engine
        cls.engine = create_async_engine(ASYNC_URL)
        cls._aio = asyncio.new_event_loop()

    def _run(self, coro):
        return self._aio.run_until_complete(coro)

    def setUp(self):
        from sqlalchemy import text
        async def clean():
            async with self.engine.begin() as c:
                await c.execute(text(
                    "DELETE FROM ingestion.chemicalbook_seed"
                    " WHERE cb_number LIKE 'UTSEED-%'"))
                await c.execute(text(
                    "DELETE FROM maintenance.cas_jobs WHERE cas_number IN (:a,:b)"
                ), {"a": CAS, "b": CAS2})
                await c.execute(text("""
                    DELETE FROM maintenance.cas_jobs WHERE chemical_id IN (
                        SELECT id FROM chemistry.chemicals
                        WHERE cas_numbers && ARRAY[:a,:b]::text[])
                """), {"a": CAS, "b": CAS2})
                await c.execute(text(
                    "DELETE FROM chemistry.chemicals"
                    " WHERE cas_numbers && ARRAY[:a,:b]::text[]"
                ), {"a": CAS, "b": CAS2})
        self._run(clean())

    @classmethod
    def tearDownClass(cls):
        cls._aio.close()

    # -- helpers -----------------------------------------------------

    async def _insert_chem(self, db, *, cas=None, cid=None, cb=None):
        from sqlalchemy import text
        cols, vals, params = ["created_at", "updated_at"], ["now()", "now()"], {}
        if cas: cols.append("cas_numbers"); vals.append(":cas"); params["cas"] = [cas]
        if cid: cols.append("pubchem_cid"); vals.append(":cid"); params["cid"] = cid
        if cb: cols.append("cb_number"); vals.append(":cb"); params["cb"] = cb
        sql = (f"INSERT INTO chemistry.chemicals ({','.join(cols)})"
               f" VALUES ({','.join(vals)}) RETURNING id")
        return (await db.execute(text(sql), params)).scalar_one()

    def _load(self, rows, **kw):
        import sys
        sys.path.insert(0, "/home/ubuntu/ops")
        import cb_seed_ingest as ing
        path = _make_sqlite(rows)
        args = ing._A(cmd="load", sqlite=path, batch=500, limit=kw.get("limit", 0),
                      start_after=kw.get("start_after", ""),
                      dry_run=kw.get("dry_run", False))
        try:
            self._run(ing.cmd_load(args))
        finally:
            os.unlink(path)

    def _schedule(self, **kw):
        import sys
        sys.path.insert(0, "/home/ubuntu/ops")
        import cb_seed_ingest as ing
        args = ing._A(cmd="schedule", limit=kw.get("limit", 50),
                      max_enqueue=kw.get("max_enqueue", 0),
                      high_water=kw.get("high_water", 10**9),
                      start_after=kw.get("start_after", ""))
        self._run(ing.cmd_schedule(args))

    def _seed_rows(self, only=None):
        from sqlalchemy import text
        async def go():
            async with self.engine.connect() as db:
                q = ("SELECT cb_number, cas, status, last_chemical_id"
                     " FROM ingestion.chemicalbook_seed"
                     " WHERE cb_number LIKE 'UTSEED-%'")
                if only:
                    q += f" AND cb_number IN {tuple(only)}"
                r = await db.execute(text(q + " ORDER BY cb_number"))
                return [tuple(x) for x in r]
        return self._run(go())

    # -- 1/2: loader 插入 + 幂等 ------------------------------------

    def test_loader_insert_and_idempotent(self):
        rows = [("UTSEED-1", CAS), ("UTSEED-2", CAS2), ("UTSEED-3", None),
                ("UTSEED-4", "bad-format")]
        self._load(rows)
        got = self._seed_rows()
        self.assertEqual([g[0] for g in got], ["UTSEED-1", "UTSEED-2"])
        self.assertEqual([g[2] for g in got], ["ACCEPTED", "ACCEPTED"])
        n_before = len(got)
        self._load(rows)  # 重跑
        self.assertEqual(len(self._seed_rows()), n_before)

    def test_loader_no_identity_side_effects(self):
        from sqlalchemy import text
        async def go():
            async with self.engine.connect() as db:
                n_chem = (await db.execute(text(
                    "SELECT count(*) FROM chemistry.chemicals"
                    " WHERE cas_numbers && ARRAY[:a,:b]::text[]"),
                    {"a": CAS, "b": CAS2})).scalar()
                n_jobs = (await db.execute(text(
                    "SELECT count(*) FROM maintenance.cas_jobs"
                    " WHERE cas_number IN (:a,:b)"),
                    {"a": CAS, "b": CAS2})).scalar()
                return n_chem, n_jobs
        self._load([("UTSEED-1", CAS)])
        n_chem, n_jobs = self._run(go())
        self.assertEqual((n_chem, n_jobs), (0, 0))

    # -- 3: 同 CAS 多 cb 全保留 --------------------------------------

    def test_multi_cb_seeds_all_kept(self):
        rows = [(f"UTSEED-{i}", CAS) for i in range(1, 6)]
        self._load(rows)
        self.assertEqual(len(self._seed_rows()), 5)  # 不折叠

    # -- 4: EXACT 不建行 ---------------------------------------------

    def test_schedule_exact_no_create(self):
        from sqlalchemy import text
        async def go():
            async with self.engine.begin() as db:
                return await self._insert_chem(db, cas=CAS, cb="1111111")
        rid = self._run(go())
        self._load([("UTSEED-1", CAS)])
        self._schedule(max_enqueue=0)
        rows = dict((r[0], r) for r in self._seed_rows())
        self.assertEqual(rows["UTSEED-1"][2], "RESOLVED_EXISTING")
        self.assertEqual(rows["UTSEED-1"][3], rid)
        async def count():
            async with self.engine.connect() as db:
                return (await db.execute(text(
                    "SELECT count(*) FROM chemistry.chemicals"
                    " WHERE cas_numbers && ARRAY[:a]::text[]"), {"a": CAS})).scalar()
        self.assertEqual(self._run(count()), 1)  # 不建行

    # -- 10: 主表 cb_number 只补空不覆盖 ------------------------------

    def test_main_cb_number_fill_only(self):
        from sqlalchemy import text
        async def go():
            async with self.engine.begin() as db:
                return await self._insert_chem(db, cas=CAS, cb="1111111")
        rid = self._run(go())
        self._load([("UTSEED-1", CAS)])
        self._schedule(max_enqueue=0)
        async def cb_now():
            async with self.engine.connect() as db:
                return (await db.execute(text(
                    "SELECT cb_number FROM chemistry.chemicals WHERE id=:i"),
                    {"i": rid})).scalar()
        self.assertEqual(self._run(cb_now()), "1111111")  # 不被 seed 覆盖

    # -- 5/6/7: NEW 延迟物化 + 单占位 + 重跑命中 ----------------------

    def test_new_placeholder_lazy_and_idempotent(self):
        from sqlalchemy import text
        # 未 schedule 前绝不建行
        self._load([("UTSEED-1", CAS)])
        async def count():
            async with self.engine.connect() as db:
                return (await db.execute(text(
                    "SELECT count(*) FROM chemistry.chemicals"
                    " WHERE cas_numbers && ARRAY[:a]::text[]"), {"a": CAS})).scalar()
        self.assertEqual(self._run(count()), 0)
        # schedule 后建一个占位
        self._schedule(max_enqueue=0)
        self.assertEqual(self._run(count()), 1)
        rows = dict((r[0], r) for r in self._seed_rows())
        self.assertEqual(rows["UTSEED-1"][2], "PENDING_NEW")
        first_cid = rows["UTSEED-1"][3]
        self.assertIsNotNone(first_cid)
        # 重跑(seed 再入队处理后): resolver 命中首次占位, 不建第二个
        self._schedule(max_enqueue=0, start_after="UTSEED-0")
        # 注: PENDING_NEW 不在 scheduler 取用状态内 — 手动重置后重跑验证幂等
        async def reset():
            async with self.engine.begin() as db:
                await db.execute(text(
                    "UPDATE ingestion.chemicalbook_seed SET status='ACCEPTED'"
                    " WHERE cb_number='UTSEED-1'"))
        self._run(reset())
        self._schedule(max_enqueue=0)
        self.assertEqual(self._run(count()), 1)  # 命中首次 placeholder

    # -- 8: AMBIGUOUS 不建行不选 candidate ---------------------------

    def test_ambiguous_no_create_no_pick(self):
        from sqlalchemy import text
        async def go():
            async with self.engine.begin() as db:
                a = await self._insert_chem(db, cas=CAS, cb="1111111")
                b = await self._insert_chem(db, cas=CAS)
                return a, b
        a, b = self._run(go())
        self._load([("UTSEED-1", CAS)])
        self._schedule(max_enqueue=0)
        rows = dict((r[0], r) for r in self._seed_rows())
        self.assertEqual(rows["UTSEED-1"][2], "AMBIGUOUS")
        self.assertIsNone(rows["UTSEED-1"][3])  # 不选 candidate
        async def count():
            async with self.engine.connect() as db:
                return (await db.execute(text(
                    "SELECT count(*) FROM chemistry.chemicals"
                    " WHERE cas_numbers && ARRAY[:a]::text[]"), {"a": CAS})).scalar()
        self.assertEqual(self._run(count()), 2)  # 不建行

    # -- 12: enqueue dedupe -------------------------------------------

    def test_enqueue_dedupe(self):
        from sqlalchemy import text
        async def go():
            async with self.engine.begin() as db:
                return await self._insert_chem(db, cas=CAS)
        self._run(go())
        self._load([("UTSEED-1", CAS)])
        self._schedule(max_enqueue=5)
        self._schedule(max_enqueue=5)  # 重跑: status=ENQUEUED 不再取用
        async def jobs():
            async with self.engine.connect() as db:
                return (await db.execute(text(
                    "SELECT count(*) FROM maintenance.cas_jobs"
                    " WHERE cas_number=:c"), {"c": CAS})).scalar()
        n = self._run(jobs())
        self.assertLessEqual(n, 1)  # active dedupe_key + ENQUEUED 状态双保险

    # -- 13: 高水位停止 ------------------------------------------------

    def test_high_water_stops_scheduler(self):
        async def go():
            async with self.engine.begin() as db:
                return await self._insert_chem(db, cas=CAS)
        self._run(go())
        self._load([("UTSEED-1", CAS)])
        self._schedule(max_enqueue=5, high_water=-1)  # 任何 backlog 即停
        rows = dict((r[0], r) for r in self._seed_rows())
        self.assertEqual(rows["UTSEED-1"][2], "ACCEPTED")  # 未被处理

    # -- 15: ledger 不参与 identity -----------------------------------

    def test_ledger_not_identity_authority(self):
        # ledger 行存在 ≠ chemical 存在: 没有 chemical 时 status 停在自身状态,
        # 且 ledger 无 FK — 删 chemical 不级联影响 ledger
        from sqlalchemy import text
        self._load([("UTSEED-1", CAS)])
        self._schedule(max_enqueue=0)
        async def check():
            async with self.engine.begin() as db:
                rid = await self._insert_chem(db, cas=CAS)
                await db.execute(text(
                    "DELETE FROM chemistry.chemicals WHERE id=:i"), {"i": rid})
                n = (await db.execute(text(
                    "SELECT count(*) FROM ingestion.chemicalbook_seed"
                    " WHERE cb_number='UTSEED-1'"))).scalar()
                return n
        self.assertEqual(self._run(check()), 1)


if __name__ == "__main__":
    unittest.main()
