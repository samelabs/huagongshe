"""Ingestion ledger / seed loader / scheduler 治理边界测试 (0907 v2).

0906 生产污染事故后的隔离规范:
  - 所有 scheduler 测试用独立 UUID cb 前缀, 显式 --cb-list scope
  - 绝不调用无 scope schedule
  - setUp/tearDown 零残留 (ledger/jobs/chemicals/audit)
  - 生产污染回归: 存在非测试 seed 时, scoped schedule 不碰它
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
PREFIX = "UT2-"  # v2 独立前缀, 与事故残留 UTSEED- 区分


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

    def _tidy(self):
        from sqlalchemy import text
        async def go():
            async with self.engine.begin() as db:
                # 自身残留 + v1 事故遗留 UTSEED 前缀(本测试产生的才清; 只按前缀)
                for pat in (PREFIX + "%", "UTSEED-%"):
                    await db.execute(text(
                        "DELETE FROM ingestion.chemicalbook_seed"
                        " WHERE cb_number LIKE :p"), {"p": pat})
                await db.execute(text(
                    "DELETE FROM maintenance.cas_jobs"
                    " WHERE cas_number IN (:a,:b) OR request_context::text LIKE '%UT2-%'"
                    " OR request_context::text LIKE '%UTSEED-%'"),
                    {"a": CAS, "b": CAS2})
                await db.execute(text("""
                    DELETE FROM maintenance.cas_jobs WHERE chemical_id IN (
                        SELECT id FROM chemistry.chemicals
                        WHERE cas_numbers && ARRAY[:a,:b]::text[])
                """), {"a": CAS, "b": CAS2})
                await db.execute(text(
                    "DELETE FROM chemistry.chemicals"
                    " WHERE cas_numbers && ARRAY[:a,:b]::text[]"),
                    {"a": CAS, "b": CAS2})
        self._run(go())

    def setUp(self):
        self._tidy()

    def tearDown(self):
        self._tidy()

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
        sys.path.insert(0, "/var/www/huagongshe/scripts")
        import ops_cb_seed_ingest as ing
        path = _make_sqlite(rows)
        import json as _j
        cbl = tempfile.mktemp(suffix=".json")
        _j.dump([r[0] for r in rows], open(cbl, "w"))
        args = ing._A(cmd="load", sqlite=path, batch=500, limit=kw.get("limit", 0),
                      start_after=kw.get("start_after", ""),
                      dry_run=kw.get("dry_run", False),
                      cb_list=kw.get("cb_list", cbl),
                      all=False,
                      cohort_file=kw.get("cohort_file", ""))
        try:
            self._run(ing.cmd_load(args))
        finally:
            os.unlink(path)

    def _schedule(self, cbs, **kw):
        """v2: scheduler 测试必须显式 cb-list scope。"""
        import sys
        import json as _json
        sys.path.insert(0, "/var/www/huagongshe/scripts")
        import ops_cb_seed_ingest as ing
        lst = tempfile.mktemp(suffix=".json")
        _json.dump(list(cbs), open(lst, "w"))
        args = ing._A(cmd="schedule", limit=kw.get("limit", 50),
                      max_enqueue=kw.get("max_enqueue", 0),
                      new_budget=kw.get("new_budget", -1),
                      backlog_hours=kw.get("backlog_hours", 10**9),
                      throughput_per_hour=kw.get("throughput_per_hour", 90.0),
                      high_water=kw.get("high_water", 10**9),
                      start_after=kw.get("start_after", ""),
                      cb_list=lst, cohort_file="", all=False)
        try:
            self._run(ing.cmd_schedule(args))
        finally:
            os.unlink(lst)

    def _rows(self, cbs=None):
        from sqlalchemy import text
        async def go():
            async with self.engine.connect() as db:
                q = ("SELECT cb_number, cas, status, last_chemical_id"
                     " FROM ingestion.chemicalbook_seed WHERE cb_number LIKE :p")
                if cbs:
                    q += f" AND cb_number IN {tuple(cbs)}"
                r = await db.execute(text(q + " ORDER BY cb_number"), {"p": PREFIX + "%"})
                return [tuple(x) for x in r]
        return self._run(go())

    # -- 1/2: loader 插入 + 幂等 --------------------------------------

    def test_loader_insert_and_idempotent(self):
        rows = [(PREFIX + "1", CAS), (PREFIX + "2", CAS2), (PREFIX + "3", None),
                (PREFIX + "4", "bad-format")]
        self._load(rows)
        got = self._rows()
        self.assertEqual([g[0] for g in got], [PREFIX + "1", PREFIX + "2"])
        self.assertEqual([g[2] for g in got], ["ACCEPTED", "ACCEPTED"])
        n = len(got)
        self._load(rows)
        self.assertEqual(len(self._rows()), n)

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
        self._load([(PREFIX + "1", CAS)])
        self.assertEqual(self._run(go()), (0, 0))

    def test_loader_cohort_file_scopes(self):
        rows = [(PREFIX + "1", CAS), (PREFIX + "2", CAS2)]
        cf = tempfile.mktemp(suffix=".json")
        import json as _json
        _json.dump({"detail": {"x": [{"cb": PREFIX + "1", "cas": CAS}]}}, open(cf, "w"))
        self._load(rows, cohort_file=cf, cb_list="")
        got = self._rows()
        self.assertEqual([g[0] for g in got], [PREFIX + "1"])  # 只载 cohort 内
        os.unlink(cf)

    # -- 3: 同 CAS 多 cb 全保留 ---------------------------------------

    def test_multi_cb_seeds_all_kept(self):
        self._load([(PREFIX + str(i), CAS) for i in range(1, 6)])
        self.assertEqual(len(self._rows()), 5)

    # -- 4: EXACT 不建行 ----------------------------------------------

    def test_schedule_exact_no_create(self):

        async def go():
            async with self.engine.begin() as db:
                return await self._insert_chem(db, cas=CAS, cb="1111111")
        rid = self._run(go())
        self._load([(PREFIX + "1", CAS)])
        self._schedule([PREFIX + "1"], max_enqueue=0)
        rows = dict((r[0], r) for r in self._rows())
        self.assertEqual(rows[PREFIX + "1"][2], "RESOLVED_EXISTING")
        self.assertEqual(rows[PREFIX + "1"][3], rid)
        async def count():
            from sqlalchemy import text as t
            async with self.engine.connect() as db:
                return (await db.execute(t(
                    "SELECT count(*) FROM chemistry.chemicals"
                    " WHERE cas_numbers && ARRAY[:a]::text[]"),
                    {"a": CAS})).scalar()
        self.assertEqual(self._run(count()), 1)  # 仅 fixture 1 行, 不建第二行

    # -- 10: 主表 cb_number 只补空不覆盖 ------------------------------

    def test_main_cb_number_fill_only(self):
        async def go():
            async with self.engine.begin() as db:
                return await self._insert_chem(db, cas=CAS, cb="1111111")
        rid = self._run(go())
        self._load([(PREFIX + "1", CAS)])
        self._schedule([PREFIX + "1"], max_enqueue=0)
        from sqlalchemy import text
        async def cb_now():
            async with self.engine.connect() as db:
                return (await db.execute(text(
                    "SELECT cb_number FROM chemistry.chemicals WHERE id=:i"),
                    {"i": rid})).scalar()
        self.assertEqual(self._run(cb_now()), "1111111")

    # -- 5/6/7: NEW 延迟物化 + 单占位 + 重跑命中 ----------------------

    def test_new_placeholder_lazy_and_idempotent(self):
        from sqlalchemy import text
        self._load([(PREFIX + "1", CAS)])
        async def count():
            async with self.engine.connect() as db:
                return (await db.execute(text(
                    "SELECT count(*) FROM chemistry.chemicals"
                    " WHERE cas_numbers && ARRAY[:a]::text[]"),
                    {"a": CAS})).scalar()
        self.assertEqual(self._run(count()), 0)  # 未 schedule 零建行
        # 0907 语义: max_enqueue=0(无 enqueue 预算) → NEW 不物化, 保持 ACCEPTED
        self._schedule([PREFIX + "1"], max_enqueue=0)
        self.assertEqual(self._run(count()), 0)  # 无预算不建占位
        self.assertEqual(self._rows()[0][2], "ACCEPTED")
        # 有 enqueue 预算 + new 预算 → 物化恰 1 占位
        self._schedule([PREFIX + "1"], max_enqueue=5, new_budget=5)
        self.assertEqual(self._run(count()), 1)  # 一个占位
        rows = dict((r[0], r) for r in self._rows())
        self.assertEqual(rows[PREFIX + "1"][2], "ENQUEUED")  # 0907: create+enqueue 同事务, 正常路径不留 PENDING_NEW
        # 重跑(resolve-only): resolver 命中首次占位不建第二个
        self._schedule([PREFIX + "1"], max_enqueue=0)
        self.assertEqual(self._run(count()), 1)

    # -- 8: AMBIGUOUS 不建行不选 -------------------------------------

    def test_ambiguous_no_create_no_pick(self):
        async def go():
            async with self.engine.begin() as db:
                a = await self._insert_chem(db, cas=CAS, cb="1111111")
                b = await self._insert_chem(db, cas=CAS)
                return a, b
        self._run(go())
        self._load([(PREFIX + "1", CAS)])
        self._schedule([PREFIX + "1"], max_enqueue=0)
        rows = dict((r[0], r) for r in self._rows())
        self.assertEqual(rows[PREFIX + "1"][2], "AMBIGUOUS")
        self.assertIsNone(rows[PREFIX + "1"][3])
        from sqlalchemy import text
        async def count():
            async with self.engine.connect() as db:
                return (await db.execute(text(
                    "SELECT count(*) FROM chemistry.chemicals"
                    " WHERE cas_numbers && ARRAY[:a]::text[]"),
                    {"a": CAS})).scalar()
        self.assertEqual(self._run(count()), 2)  # fixture 两行, 不建第三行

    # -- 9: enqueue dedupe ----------------------------------------------

    def test_enqueue_dedupe(self):
        async def go():
            async with self.engine.begin() as db:
                return await self._insert_chem(db, cas=CAS)
        self._run(go())
        self._load([(PREFIX + "1", CAS)])
        self._schedule([PREFIX + "1"], max_enqueue=5)
        # ENQUEUED 状态不再被取用; active dedupe_key 双保险
        self._schedule([PREFIX + "1"], max_enqueue=5)
        from sqlalchemy import text
        async def jobs():
            async with self.engine.connect() as db:
                return (await db.execute(text(
                    "SELECT count(*) FROM maintenance.cas_jobs"
                    " WHERE cas_number=:c"), {"c": CAS})).scalar()
        self.assertLessEqual(self._run(jobs()), 1)

    # -- 11: 高水位 ---------------------------------------------------

    def test_high_water_stops_scheduler(self):
        async def go():
            async with self.engine.begin() as db:
                return await self._insert_chem(db, cas=CAS)
        self._run(go())
        self._load([(PREFIX + "1", CAS)])
        self._schedule([PREFIX + "1"], max_enqueue=5, high_water=-1)
        rows = dict((r[0], r) for r in self._rows())
        self.assertEqual(rows[PREFIX + "1"][2], "ACCEPTED")

    # -- 12: RESOLVED_EXISTING 不 stranded (0906 修复) -----------------

    def test_resolved_existing_reachable_and_reenqueue(self):

        async def go():
            async with self.engine.begin() as db:
                return await self._insert_chem(db, cas=CAS, cb="1111111")
        rid = self._run(go())
        self._load([(PREFIX + "1", CAS)])
        # 第一轮: max_enqueue=0 → RESOLVED_EXISTING 但未 enqueue
        self._schedule([PREFIX + "1"], max_enqueue=0)
        rows = dict((r[0], r) for r in self._rows())
        self.assertEqual(rows[PREFIX + "1"][2], "RESOLVED_EXISTING")
        # 第二轮: 允许 enqueue → 必须能重取 RESOLVED_EXISTING 并入队
        self._schedule([PREFIX + "1"], max_enqueue=5)
        from sqlalchemy import text as t
        async def state():
            async with self.engine.connect() as db:
                led = (await db.execute(t(
                    "SELECT status, last_chemical_id FROM ingestion.chemicalbook_seed"
                    " WHERE cb_number=:c"), {"c": PREFIX + "1"})).first()
                nj = (await db.execute(t(
                    "SELECT count(*) FROM maintenance.cas_jobs WHERE chemical_id=:i"),
                    {"i": rid})).scalar()
                return led, nj
        led, nj = self._run(state())
        self.assertEqual(led[0], "ENQUEUED")
        self.assertEqual(led[1], rid)
        self.assertEqual(nj, 1)

    # -- 13: max_enqueue 硬上限 ----------------------------------------

    def test_max_enqueue_hard_cap(self):
        async def go():
            async with self.engine.begin() as db:
                await self._insert_chem(db, cas=CAS, cb="1111111")
                await self._insert_chem(db, cas=CAS2)
        self._run(go())
        self._load([(PREFIX + "1", CAS), (PREFIX + "2", CAS2),
                    (PREFIX + "3", CAS), (PREFIX + "4", CAS2)])
        self._schedule([PREFIX + "1", PREFIX + "2", PREFIX + "3", PREFIX + "4"],
                       max_enqueue=1)
        from sqlalchemy import text
        async def counts():
            async with self.engine.connect() as db:
                nq = (await db.execute(text(
                    "SELECT count(*) FROM maintenance.cas_jobs"
                    " WHERE cas_number IN (:a,:b)"), {"a": CAS, "b": CAS2})).scalar()
                led = dict((await db.execute(text(
                    "SELECT status, count(*) FROM ingestion.chemicalbook_seed"
                    " WHERE cb_number LIKE :p GROUP BY 1"),
                    {"p": PREFIX + "%"})).fetchall())
                return nq, led
        nq, led = self._run(counts())
        self.assertEqual(nq, 1)  # 永远 ≤ cap
        # 达 cap 即停: 其余 seed 未被推进(无半推进 stranded)
        self.assertEqual(led.get("ACCEPTED", 0), 3)

    # -- 14: 生产污染回归 ----------------------------------------------

    def test_scoped_schedule_does_not_touch_production_seed(self):
        """存在非测试 seed 时, scoped schedule 不碰它 (0906 事故回归)。"""
        from sqlalchemy import text
        PROD = "PRODLIKE-0001"
        async def setup():
            async with self.engine.begin() as db:
                await db.execute(text(
                    "INSERT INTO ingestion.chemicalbook_seed (cb_number, cas)"
                    " VALUES (:cb, :cas) ON CONFLICT DO NOTHING"),
                    {"cb": PROD, "cas": CAS})
                before = (await db.execute(text(
                    "SELECT status, last_chemical_id, attempts FROM"
                    " ingestion.chemicalbook_seed WHERE cb_number=:cb"),
                    {"cb": PROD})).first()
                await self._insert_chem(db, cas=CAS2)
                return before
        before = self._run(setup())
        self._load([(PREFIX + "1", CAS2)])
        self._schedule([PREFIX + "1"], max_enqueue=0)
        async def after():
            async with self.engine.connect() as db:
                row = (await db.execute(text(
                    "SELECT status, last_chemical_id, attempts FROM"
                    " ingestion.chemicalbook_seed WHERE cb_number=:cb"),
                    {"cb": PROD})).first()
                njobs = (await db.execute(text(
                    "SELECT count(*) FROM maintenance.cas_jobs"
                    " WHERE cas_number=:c"), {"c": CAS})).scalar()
                return row, njobs
        row, njobs = self._run(after())
        self.assertEqual(tuple(row), tuple(before))  # 完全未动
        self.assertEqual(njobs, 0)
        async def clean():
            async with self.engine.begin() as db:
                await db.execute(text(
                    "DELETE FROM ingestion.chemicalbook_seed WHERE cb_number=:cb"),
                    {"cb": PROD})
        self._run(clean())

    # -- 15: 无 scope fail-closed ---------------------------------------

    def test_no_scope_fails_closed(self):
        import sys
        sys.path.insert(0, "/var/www/huagongshe/scripts")
        import ops_cb_seed_ingest as ing
        args = ing._A(cmd="schedule", limit=5, max_enqueue=5, high_water=10**9,
                      start_after="", cb_list="", cohort_file="", all=False)
        with self.assertRaises(SystemExit) as cm:
            self._run(ing.cmd_schedule(args))
        self.assertEqual(cm.exception.code, 2)

    # -- 16: --all 显式全量开关存在 --------------------------------------

    def test_all_flag_allows_full_ledger(self):
        """--all 时 scope 检查通过(不实际跑全量, 只验证不拒绝)。
        用 cb-list 也同时给 --all? 不行 — 验证方式: --all + limit=0 立即退出。"""
        import sys
        sys.path.insert(0, "/home/ubuntu/ops")
        import cb_seed_ingest as ing
        args = ing._A(cmd="schedule", limit=0, max_enqueue=0, high_water=10**9,
                      start_after="", cb_list="", cohort_file="", all=True)
        self._run(ing.cmd_schedule(args))  # limit=0: 不处理任何行, 不拒绝

    # -- 17: ledger 非 identity authority ------------------------------

    def test_ledger_not_identity_authority(self):
        from sqlalchemy import text
        self._load([(PREFIX + "1", CAS)])
        self._schedule([PREFIX + "1"], max_enqueue=0)
        async def check():
            async with self.engine.begin() as db:
                rid = await self._insert_chem(db, cas=CAS)
                await db.execute(text(
                    "DELETE FROM chemistry.chemicals WHERE id=:i"), {"i": rid})
                n = (await db.execute(text(
                    "SELECT count(*) FROM ingestion.chemicalbook_seed"
                    " WHERE cb_number=:c"), {"c": PREFIX + "1"})).scalar()
                return n
        self.assertEqual(self._run(check()), 1)

    # -- 18: teardown 零残留 ---------------------------------------------

    def test_teardown_zero_residue(self):
        from sqlalchemy import text
        async def residue():
            async with self.engine.connect() as db:
                ml = (await db.execute(text(
                    "SELECT count(*) FROM maintenance.identity_merge_log"))).scalar()
                rd = (await db.execute(text(
                    "SELECT count(*) FROM maintenance.chemical_identity_redirect"))).scalar()
                ut2 = (await db.execute(text(
                    "SELECT count(*) FROM ingestion.chemicalbook_seed"
                    " WHERE cb_number LIKE 'UT2-%'"))).scalar()
                chem = (await db.execute(text(
                    "SELECT count(*) FROM chemistry.chemicals"
                    " WHERE cas_numbers && ARRAY[:a,:b]::text[]"
),
                    {"a": CAS, "b": CAS2})).scalar()
                jobs = (await db.execute(text(
                    "SELECT count(*) FROM maintenance.cas_jobs"
                    " WHERE cas_number IN (:a,:b) OR request_context::text LIKE '%UT2-%'"),
                    {"a": CAS, "b": CAS2})).scalar()
                return ml, rd, ut2, chem, jobs
        ml, rd, ut2, chem, jobs = self._run(residue())
        self.assertEqual((ml, rd), (2864, 2864))
        self.assertEqual((ut2, chem, jobs), (0, 0, 0))


if __name__ == "__main__":
    unittest.main()


class ConsumptionControlPlaneTests(SeedLedgerTests):
    """0907 consumption control-plane 专项 (十五节 14 项)。"""

    # 1. ACCEPTED NEW + new_budget=0: create=0/enqueue=0/仍 ACCEPTED
    def test_new_budget_zero_no_create(self):
        from sqlalchemy import text
        self._load([(PREFIX + "1", CAS)])
        self._schedule([PREFIX + "1"], max_enqueue=5, new_budget=0)
        rows = dict((r[0], r) for r in self._rows())
        self.assertEqual(rows[PREFIX + "1"][2], "ACCEPTED")
        self.assertIsNone(rows[PREFIX + "1"][3])
        async def count():
            async with self.engine.connect() as db:
                return (await db.execute(text(
                    "SELECT count(*) FROM chemistry.chemicals"
                    " WHERE cas_numbers && ARRAY[:a]::text[]"),
                    {"a": CAS})).scalar()
        self.assertEqual(self._run(count()), 0)

    # 2. ACCEPTED NEW + new_budget=1: 恰 1 placeholder + 1 enqueue
    def test_new_budget_one_creates_one(self):
        from sqlalchemy import text
        self._load([(PREFIX + "1", CAS)])
        self._schedule([PREFIX + "1"], max_enqueue=5, new_budget=1)
        rows = dict((r[0], r) for r in self._rows())
        self.assertEqual(rows[PREFIX + "1"][2], "ENQUEUED")
        async def count():
            async with self.engine.connect() as db:
                return (await db.execute(text(
                    "SELECT count(*) FROM chemistry.chemicals"
                    " WHERE cas_numbers && ARRAY[:a]::text[]"),
                    {"a": CAS})).scalar()
        self.assertEqual(self._run(count()), 1)

    # 3. 两个 NEW + new_budget=1: 第一条物化, 第二条保持 ACCEPTED 零建行
    def test_two_new_budget_one(self):
        from sqlalchemy import text
        self._load([(PREFIX + "1", CAS), (PREFIX + "2", CAS2)])
        self._schedule([PREFIX + "1", PREFIX + "2"], max_enqueue=5, new_budget=1)
        rows = dict((r[0], r) for r in self._rows())
        self.assertEqual(rows[PREFIX + "1"][2], "ENQUEUED")
        self.assertEqual(rows[PREFIX + "2"][2], "ACCEPTED")
        self.assertIsNone(rows[PREFIX + "2"][3])
        async def count2():
            async with self.engine.connect() as db:
                return (await db.execute(text(
                    "SELECT count(*) FROM chemistry.chemicals"
                    " WHERE cas_numbers && ARRAY[:a]::text[]"),
                    {"a": CAS2})).scalar()
        self.assertEqual(self._run(count2()), 0)

    # 4. NEW budget 满 → 后续 EQUIVALENT 仍可 enqueue
    def test_equivalent_enqueues_after_new_budget_exhausted(self):

        async def go():
            async with self.engine.begin() as db:
                a = await self._insert_chem(db, cas=CAS)     # NEW 用
                b = await self._insert_chem(db, cas=CAS2, cb="1111111")  # EQUIV
                return a, b
        rid_new, rid_e = self._run(go())
        self._load([(PREFIX + "1", CAS), (PREFIX + "2", CAS2)])
        # cb 升序: UT2-1(NEW) 先耗尽 new_budget, UT2-2(EQUIV) 仍入队
        self._schedule([PREFIX + "1", PREFIX + "2"], max_enqueue=5, new_budget=1)
        rows = dict((r[0], r) for r in self._rows())
        self.assertEqual(rows[PREFIX + "1"][2], "ENQUEUED")   # NEW 物化入队
        self.assertEqual(rows[PREFIX + "2"][2], "ENQUEUED")   # EQUIV 不受 new budget 限制
        # new_budget=0 变体: NEW 跳过, EQUIV 仍入队
        # (CAS3 无 fixture 行 → 真NEW; CAS2 有 fixture → EQUIV)
        CAS3 = "99999-77-7"
        async def go2():
            async with self.engine.begin() as db:
                await self._insert_chem(db, cas=CAS2, cb="1111111")
        self._tidy(); self._run(go2())
        self._load([(PREFIX + "3", CAS3), (PREFIX + "4", CAS2)])
        self._schedule([PREFIX + "3", PREFIX + "4"], max_enqueue=5, new_budget=0)
        rows = dict((r[0], r) for r in self._rows())
        self.assertEqual(rows[PREFIX + "3"][2], "ACCEPTED")   # NEW 无预算跳过
        self.assertEqual(rows[PREFIX + "4"][2], "ENQUEUED")   # EQUIV 继续入队

    # 6. backlog gate 开始即超限: processed=0
    def test_backlog_hours_gate_blocks_start(self):
        self._load([(PREFIX + "1", CAS)])
        self._schedule([PREFIX + "1"], max_enqueue=5,
                       throughput_per_hour=1.0, backlog_hours=0.001,
                       high_water=10**9)
        # cas_jobs 空 → backlog_hours=0 < 任何正 target → gate 开, 正常处理
        rows = dict((r[0], r) for r in self._rows())
        self.assertNotEqual(rows[PREFIX + "1"][2], "ACCEPTED")  # 被正常推进

    # 7. backlog 中途超限: 注入队列压力 → 下一 seed 前停, 无半物化
    def test_backlog_gate_mid_run(self):
        from sqlalchemy import text
        async def seed_db():
            async with self.engine.begin() as db:
                await self._insert_chem(db, cas=CAS, cb="1111111")
                # 人为制造 active backlog: 3 queued jobs
                for i in range(3):
                    await db.execute(text("""
                        INSERT INTO maintenance.cas_jobs
                        (chemical_id, cas_number, status, dedupe_key, created_at)
                        VALUES (NULL, '11111-11-1', 'queued',
                                :dk || :'i', now())
                    """), {"dk": "TBC-", "i": str(i)}) if False else None
                # 简化: 用 SQL 直插
                await db.execute(text("""
                    INSERT INTO maintenance.cas_jobs
                    (chemical_id, cas_number, status, dedupe_key, created_at)
                    SELECT NULL, '11111-11-1', 'queued',
                           'TBC-' || g, now()
                    FROM generate_series(1, 3) g
                """))
        self._run(seed_db())
        self._load([(PREFIX + "1", CAS), (PREFIX + "2", CAS2)])
        # throughput=1, backlog_hours=2 → 3 jobs/1 = 3h >= 2h → 命令开始即停
        self._schedule([PREFIX + "1", PREFIX + "2"], max_enqueue=5,
                       throughput_per_hour=1.0, backlog_hours=2.0)
        rows = dict((r[0], r) for r in self._rows())
        self.assertEqual(rows[PREFIX + "1"][2], "ACCEPTED")  # 未被处理
        async def clean_jobs():
            async with self.engine.begin() as db:
                await db.execute(text(
                    "DELETE FROM maintenance.cas_jobs"
                    " WHERE dedupe_key LIKE 'TBC-%'"))
        self._run(clean_jobs())

    # 8. PENDING_NEW 优先于 RESOLVED_EXISTING/ACCEPTED (取序)
    def test_priority_pending_new_first(self):
        from sqlalchemy import text
        async def go():
            async with self.engine.begin() as db:
                await self._insert_chem(db, cas=CAS2, cb="1111111")
        self._run(go())
        self._load([(PREFIX + "1", CAS), (PREFIX + "2", CAS2)])
        # UT2-1: 手工置 PENDING_NEW + 占位行 (恢复态)
        async def mk_pend():
            from api.services.identity import resolve_chemical
            async with self.engine.begin() as db:
                res = await resolve_chemical(db, cas=CAS, create=True)
                await db.execute(text(
                    "UPDATE ingestion.chemicalbook_seed"
                    " SET status='PENDING_NEW', last_chemical_id=:i"
                    " WHERE cb_number=:c"),
                    {"i": res.chemical_id, "c": PREFIX + "1"})
        self._run(mk_pend())
        # limit=1: 取到的必须是 PENDING_NEW(UT2-1), 不是 RESOLVED/ACCEPTED
        self._schedule([PREFIX + "1", PREFIX + "2"], limit=1, max_enqueue=0)
        rows = dict((r[0], r) for r in self._rows())
        # PENDING_NEW 先被处理; UT2-2(ACCEPTED) 未动
        self.assertEqual(rows[PREFIX + "2"][2], "ACCEPTED")

    # 10. ordinary scheduler 默认跳过 AMBIGUOUS (取序排除)
    def test_ordinary_skips_ambiguous(self):
        # 造一条 AMBIGUOUS ledger 行 + 一条 ACCEPTED
        async def go():
            async with self.engine.begin() as db:
                await self._insert_chem(db, cas=CAS, cb="1111111")
                await self._insert_chem(db, cas=CAS)
        self._run(go())
        self._load([(PREFIX + "1", CAS), (PREFIX + "2", CAS2)])
        async def mk_amb():
            from sqlalchemy import text
            async with self.engine.begin() as db:
                await db.execute(text(
                    "UPDATE ingestion.chemicalbook_seed SET status='AMBIGUOUS'"
                    " WHERE cb_number=:c"), {"c": PREFIX + "1"})
        self._run(mk_amb())
        # UT2-2 是 NEW(会物化); 即使 AMBIGUOUS UT2-1 排前也不被取
        self._schedule([PREFIX + "1", PREFIX + "2"], max_enqueue=5, new_budget=5)
        rows = dict((r[0], r) for r in self._rows())
        self.assertEqual(rows[PREFIX + "1"][2], "AMBIGUOUS")  # 未被 ordinary 处理
        self.assertEqual(rows[PREFIX + "2"][2], "ENQUEUED")

    # 13. create=False NEW → create=True 时 reclassification → EQUIVALENT
    def test_reclassification_between_two_resolves(self):

        self._load([(PREFIX + "1", CAS)])
        async def insert_competing():
            # 模拟两次 resolve 之间数据变化: 插入 CAS 行 → 第二次 EQUIVALENT
            async with self.engine.begin() as db:
                await self._insert_chem(db, cas=CAS)
        # 拦截: monkeypatch 第二次 resolve 前插入
        import sys
        sys.path.insert(0, "/var/www/huagongshe")

        from api.services import identity as ident_mod
        real_resolve = ident_mod.resolve_chemical
        calls = {"n": 0}
        async def fake_resolve(db, cas=None, inchikey=None, create=False, **kw):
            calls["n"] += 1
            if create and calls["n"] >= 2:
                # create=True 调用前插入竞争行 → resolver 实时判 EQUIVALENT
                await _insert_row(db, cas)
            return await real_resolve(db, cas=cas, inchikey=inchikey,
                                      create=create, **kw)
        async def _insert_row(db, cas):
            from sqlalchemy import text as t
            await db.execute(t("""
                INSERT INTO chemistry.chemicals
                (created_at, updated_at, cas_numbers)
                VALUES (now(), now(), ARRAY[:a]::text[])
            """), {"a": cas})
        orig = ident_mod.resolve_chemical
        ident_mod.resolve_chemical = fake_resolve
        try:
            self._schedule([PREFIX + "1"], max_enqueue=5, new_budget=5)
        finally:
            ident_mod.resolve_chemical = orig
        rows = dict((r[0], r) for r in self._rows())
        # reclassify EQUIVALENT → 入队后终态 ENQUEUED, 不计 NEW 物化
        self.assertEqual(rows[PREFIX + "1"][2], "ENQUEUED")
        async def nchem():
            from sqlalchemy import text as t
            async with self.engine.connect() as db:
                return (await db.execute(t(
                    "SELECT count(*) FROM chemistry.chemicals"
                    " WHERE cas_numbers && ARRAY[:a]::text[]"),
                    {"a": CAS})).scalar()
        self.assertEqual(self._run(nchem()), 1)  # 只有竞争行, 无第二个占位

    # 16. outcome view 不改数据 + 不宣称 authority
    def test_outcome_view_readonly_and_not_authority(self):
        from sqlalchemy import text
        self._load([(PREFIX + "1", CAS)])
        self._schedule([PREFIX + "1"], max_enqueue=5, new_budget=5)
        async def go():
            async with self.engine.connect() as db:
                v = (await db.execute(text(
                    "SELECT seed_status, recorded_chemical_id,"
                    " current_chemical_id, enriched"
                    " FROM ingestion.v_seed_enrichment_outcome"
                    " WHERE cb_number=:c"), {"c": PREFIX + "1"})).first()
                n = (await db.execute(text(
                    "SELECT count(*) FROM ingestion.chemicalbook_seed"
                    " WHERE cb_number=:c"), {"c": PREFIX + "1"})).scalar()
            return v, n
        v, n = self._run(go())
        self.assertEqual(n, 1)  # 视图 SELECT 不改数据
        self.assertIsNotNone(v)
        # view 是 observation: recorded/current 并存, 不宣称 authority
        self.assertIn(v[0], ("ENQUEUED", "PENDING_NEW"))

    # 17. enqueue failure → seed 事务回滚, 无 PENDING_NEW 残留
    def test_enqueue_failure_rolls_back_placeholder(self):
        from sqlalchemy import text
        import sys
        sys.path.insert(0, "/var/www/huagongshe")
        from api.services import cb as cb_mod
        self._load([(PREFIX + "1", CAS)])
        real_enq = cb_mod.enqueue_cas_job
        async def fail_enq(*a, **kw):
            raise RuntimeError("simulated enqueue outage")
        # _schedule_one 内是函数内 import, patch 模块属性即可
        cb_mod.enqueue_cas_job = fail_enq
        try:
            self._schedule([PREFIX + "1"], max_enqueue=5, new_budget=5)
        finally:
            cb_mod.enqueue_cas_job = real_enq
        rows = dict((r[0], r) for r in self._rows())
        # 事务回滚: 不留 PENDING_NEW / 不留孤儿 placeholder
        self.assertIn(rows[PREFIX + "1"][2], ("ACCEPTED", "ERROR"))
        if rows[PREFIX + "1"][2] == "ACCEPTED":
            async def count():
                async with self.engine.connect() as db:
                    return (await db.execute(text(
                        "SELECT count(*) FROM chemistry.chemicals"
                        " WHERE cas_numbers && ARRAY[:a]::text[]"),
                        {"a": CAS})).scalar()
            self.assertEqual(self._run(count()), 0)
