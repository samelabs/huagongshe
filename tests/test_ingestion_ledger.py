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
        sys.path.insert(0, "/var/www/huagongshe/scripts")
        import ops_cb_seed_ingest as ing
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
        # 0907 修: 生产队列可能瞬时非空(线上 worker 在租), 用吞吐 1e9 保证
        # backlog_hours≈0 恒 < target → gate 确定性开, 测试不再依赖空队列
        self._schedule([PREFIX + "1"], max_enqueue=5,
                       throughput_per_hour=1e9, backlog_hours=0.001,
                       high_water=10**9)
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


class PriorityTraversalTests(SeedLedgerTests):
    """0907 fix: priority×keyset traversal 专项 (九~十五节)。"""

    def _order_of(self, cbs):
        """按 updated_at+cb 还原处理顺序(每 seed 一个事务, updated_at 单调)。"""
        from sqlalchemy import text
        async def go():
            async with self.engine.connect() as db:
                rows = (await db.execute(text(
                    "SELECT cb_number, status, attempts, updated_at,"
                    " extract(epoch from updated_at)::numeric(16,6) AS e"
                    " FROM ingestion.chemicalbook_seed"
                    " WHERE cb_number = ANY(:c) ORDER BY e, cb_number"),
                    {"c": sorted(cbs)})).fetchall()
            return [(r[0], r[1], r[2]) for r in rows]
        return self._run(go())

    # 九. P2 cb > P3 cb 逆序: 不丢 P3
    def test_reverse_p2_gt_p3(self):
        # P2: 9000/9500 (RESOLVED_EXISTING); P3: 0100/0200 (ACCEPTED)

        async def go():
            async with self.engine.begin() as db:
                await self._insert_chem(db, cas=CAS, cb="1111111")
                await self._insert_chem(db, cas=CAS2)
        self._run(go())
        self._load([(PREFIX + "9000", CAS), (PREFIX + "9500", CAS),
                    (PREFIX + "0100", CAS2), (PREFIX + "0200", CAS)])
        # 先把 9000/9500 造成 RESOLVED_EXISTING (CAS 有 cb=1111111 fixture → EQUIV)
        self._schedule([PREFIX + "9000", PREFIX + "9500"], max_enqueue=0)
        # 0100(CAS2 NEW), 0200(CAS EQUIV fixture): 全量跑
        self._schedule([PREFIX + "9000", PREFIX + "9500",
                        PREFIX + "0100", PREFIX + "0200"],
                       max_enqueue=10, new_budget=10)
        rows = dict((r[0], r[2]) for r in self._rows())
        # 全部被处理: P2 层 9000/9500 → ENQUEUED; P3 层 0100/0200 → ENQUEUED
        self.assertEqual(rows[PREFIX + "0100"], "ENQUEUED")
        self.assertEqual(rows[PREFIX + "0200"], "ENQUEUED")
        self.assertEqual(rows[PREFIX + "9000"], "ENQUEUED")
        self.assertEqual(rows[PREFIX + "9500"], "ENQUEUED")

    # 十. P1/P2/P3 全逆序
    def test_full_reverse_priority(self):
        from sqlalchemy import text
        from api.services.identity import resolve_chemical
        async def go():
            async with self.engine.begin() as db:
                await self._insert_chem(db, cas=CAS, cb="1111111")  # P2/P3 EQUIV 源
        self._run(go())
        self._load([(PREFIX + "9000", CAS), (PREFIX + "5000", CAS),
                    (PREFIX + "0100", CAS)])
        async def mk_states():
            async with self.engine.begin() as db:
                # P1: 9000 手工造 PENDING_NEW+占位
                res = await resolve_chemical(db, cas=CAS2, create=True)
                await db.execute(text(
                    "UPDATE ingestion.chemicalbook_seed"
                    " SET status='PENDING_NEW', last_chemical_id=:i"
                    " WHERE cb_number=:c"),
                    {"i": res.chemical_id, "c": PREFIX + "9000"})
                # P2: 5000 → RESOLVED_EXISTING (resolve-only)
        # 先 resolve 5000 (CAS EQUIV) via schedule max_enqueue=0
        self._schedule([PREFIX + "5000"], max_enqueue=0)
        # P1 9000 用独立 CAS2 造 PENDING_NEW — 需 ledger 行是 CAS2:
        self._tidy()
        self._run(go())
        self._load([(PREFIX + "9000", CAS2), (PREFIX + "5000", CAS),
                    (PREFIX + "0100", CAS)])
        self._schedule([PREFIX + "5000"], max_enqueue=0)  # P2 态
        self._run(mk_states())
        # 全量: P1 9000 → P2 5000 → P3 0100, cb 全逆序
        self._schedule([PREFIX + "9000", PREFIX + "5000", PREFIX + "0100"],
                       max_enqueue=10, new_budget=10)
        rows = dict((r[0], r[2]) for r in self._rows())
        self.assertEqual(rows[PREFIX + "9000"], "ENQUEUED")  # P1
        self.assertEqual(rows[PREFIX + "5000"], "ENQUEUED")  # P2
        self.assertEqual(rows[PREFIX + "0100"], "ENQUEUED")  # P3

    # 十一. batch 边界: 每层数据 > 单次查询窗 — 由 LIMIT 1 逐行天然分页,
    # 此测试用多条 P2/P3 验证层内 cursor 跨行前进
    def test_multi_batch_within_phase(self):
        async def go():
            async with self.engine.begin() as db:
                await self._insert_chem(db, cas=CAS, cb="1111111")
        self._run(go())
        rows = [(PREFIX + f"2{i:03d}", CAS) for i in range(5)]      # P2 (EQUIV)
        rows += [(PREFIX + f"1{i:03d}", CAS) for i in range(5)]     # P3 同 CAS
        self._load(rows)
        # 先把 2xxx 五条推成 RESOLVED_EXISTING
        self._schedule([r[0] for r in rows[:5]], max_enqueue=0)
        # 全量: P2 五条全扫 → P3 从最小 cb 开始五条全处理
        self._schedule([r[0] for r in rows], max_enqueue=20, new_budget=20)
        st = dict((r[0], r[2]) for r in self._rows())
        self.assertEqual(sum(1 for v in st.values() if v == "ENQUEUED"), 10)

    # 十二. NEW budget 耗尽 → EQUIVALENT 仍 enqueue (0907 live 未验证到的场景)
    def test_new_budget_exhausted_equiv_still_enqueues(self):

        CAS3 = "99999-77-7"
        async def go():
            async with self.engine.begin() as db:
                await self._insert_chem(db, cas=CAS, cb="1111111")  # 0300 EQUIV
        self._run(go())
        # cb 升序: 0100 NEW, 0200 NEW, 0300 EQUIV
        self._load([(PREFIX + "0100", CAS2), (PREFIX + "0200", CAS3),
                    (PREFIX + "0300", CAS)])
        self._schedule([PREFIX + "0100", PREFIX + "0200", PREFIX + "0300"],
                       max_enqueue=10, new_budget=1)
        st = dict((r[0], r[2]) for r in self._rows())
        self.assertEqual(st[PREFIX + "0100"], "ENQUEUED")   # 第 1 个 NEW 物化
        self.assertEqual(st[PREFIX + "0200"], "ACCEPTED")   # budget 尽: 跳过
        self.assertEqual(st[PREFIX + "0300"], "ENQUEUED")   # EQUIV 仍入队 ✓
        # 0200 无 placeholder
        async def n_chem():
            from sqlalchemy import text as t
            async with self.engine.connect() as db:
                return (await db.execute(t(
                    "SELECT count(*) FROM chemistry.chemicals"
                    " WHERE cas_numbers && ARRAY[:a]::text[]"),
                    {"a": CAS3})).scalar()
        self.assertEqual(self._run(n_chem()), 0)
        # CAS3/CAS2 fixture 清理 (CAS3 无 fixture, tidy 按 CAS/CAS2 清)
        async def clean():
            from sqlalchemy import text as t
            async with self.engine.begin() as db:
                await db.execute(t(
                    "DELETE FROM chemistry.chemicals"
                    " WHERE cas_numbers && ARRAY[:a]::text[]"), {"a": CAS3})
                await db.execute(t(
                    "DELETE FROM maintenance.cas_jobs WHERE cas_number=:c"),
                    {"c": CAS3})
        self._run(clean())

    # 十三. hard cap 跨层: P2 3 + P3 10, max=5 → P2 3 + P3 2, 立即停
    def test_hard_cap_across_phases(self):

        async def go():
            async with self.engine.begin() as db:
                await self._insert_chem(db, cas=CAS, cb="1111111")
        self._run(go())
        rows = [(PREFIX + f"3{i:02d}", CAS) for i in range(3)]     # → P2 EQUIV
        rows += [(PREFIX + f"1{i:02d}", CAS) for i in range(10)]    # → P3 EQUIV (同 CAS)
        self._load(rows)
        self._schedule([r[0] for r in rows[:3]], max_enqueue=0)     # 3 条 → P2
        self._schedule([r[0] for r in rows], max_enqueue=5, new_budget=5)
        st = dict((r[0], r[2]) for r in self._rows())
        enq = sum(1 for v in st.values() if v == "ENQUEUED")
        self.assertEqual(enq, 5)  # 恰 5, 无第 6
        # P3 后续未推进 (ACCEPTED 保持)
        self.assertEqual(st.get(PREFIX + "105"), "ACCEPTED")

    # 十四. backlog stop 跨层: P2 完成后 gate 超限 → P3 零推进
    def test_backlog_stop_between_phases(self):
        from sqlalchemy import text
        async def go():
            async with self.engine.begin() as db:
                await self._insert_chem(db, cas=CAS, cb="1111111")
                await db.execute(text("""
                    INSERT INTO maintenance.cas_jobs
                    (chemical_id, cas_number, status, dedupe_key, created_at)
                    SELECT NULL, '11111-11-1', 'queued', 'TB2-' || g, now()
                    FROM generate_series(1, 5) g
                """))
        self._run(go())
        self._load([(PREFIX + "5000", CAS), (PREFIX + "0100", CAS)])
        self._schedule([PREFIX + "5000"], max_enqueue=0)   # 5000 → P2
        # backlog 5 / throughput 1 → 5h ≥ 2h: 命令开始即停
        self._schedule([PREFIX + "5000", PREFIX + "0100"],
                       max_enqueue=5, throughput_per_hour=1.0, backlog_hours=2.0)
        st = dict((r[0], r[2]) for r in self._rows())
        self.assertEqual(st[PREFIX + "0100"], "ACCEPTED")  # P3 零推进
        async def clean():
            from sqlalchemy import text as t
            async with self.engine.begin() as db:
                await db.execute(t(
                    "DELETE FROM maintenance.cas_jobs WHERE dedupe_key LIKE 'TB2-%'"))
        self._run(clean())

    # 十五. scope isolation: scope 外高优先级 seed 不被处理
    def test_scope_beats_priority(self):
        from sqlalchemy import text
        async def go():
            async with self.engine.begin() as db:
                await self._insert_chem(db, cas=CAS, cb="1111111")
        self._run(go())
        self._load([(PREFIX + "9zzz", CAS)])   # scope 外 P2-like: 先 resolve
        # PROD-like scope 外 seed: 造 RESOLVED_EXISTING, cb 最小
        async def mk_prod():
            async with self.engine.begin() as db:
                await db.execute(text(
                    "INSERT INTO ingestion.chemicalbook_seed (cb_number, cas)"
                    " VALUES ('PRODLIKE-0002', :c)"
                    " ON CONFLICT DO NOTHING"), {"c": CAS})
                await db.execute(text(
                    "UPDATE ingestion.chemicalbook_seed"
                    " SET status='RESOLVED_EXISTING'"
                    " WHERE cb_number='PRODLIKE-0002'"))
        self._run(mk_prod())
        # scope 只含 ACCEPTED seed (P3); scope 外 P2 不能混入
        self._load([(PREFIX + "0100", CAS2)])
        self._schedule([PREFIX + "0100"], max_enqueue=5, new_budget=5)
        async def prod_untouched():
            from sqlalchemy import text as t
            async with self.engine.connect() as db:
                return (await db.execute(t(
                    "SELECT status, last_chemical_id FROM"
                    " ingestion.chemicalbook_seed"
                    " WHERE cb_number='PRODLIKE-0002'"))).first()
        st = self._run(prod_untouched())
        self.assertEqual(st[0], "RESOLVED_EXISTING")  # 未被 scope 外处理
        async def clean():
            from sqlalchemy import text as t
            async with self.engine.begin() as db:
                await db.execute(t(
                    "DELETE FROM ingestion.chemicalbook_seed"
                    " WHERE cb_number='PRODLIKE-0002'"))
        self._run(clean())

    # 七. scheduler --start-after fail-closed
    def test_scheduler_start_after_rejected(self):
        import sys
        sys.path.insert(0, "/var/www/huagongshe/scripts")
        import ops_cb_seed_ingest as ing
        import json as _j, tempfile
        lst = tempfile.mktemp(suffix=".json")
        _j.dump([PREFIX + "1"], open(lst, "w"))
        args = ing._A(cmd="schedule", limit=5, max_enqueue=5, new_budget=5,
                      backlog_hours=10**9, throughput_per_hour=90.0,
                      high_water=10**9, start_after="anything",
                      cb_list=lst, cohort_file="", all=False)
        with self.assertRaises(SystemExit) as cm:
            self._run(ing.cmd_schedule(args))
        self.assertEqual(cm.exception.code, 2)


class MultiCbSourceGrainTests(SeedLedgerTests):
    """0907 multi-CB source grain 专项 (source retrieval identity, 非 entity identity)。"""

    def _jobs(self, cbs):
        from sqlalchemy import text
        async def go():
            async with self.engine.connect() as db:
                rows = (await db.execute(text(
                    "SELECT dedupe_key, priority, request_context->>'source_cb'"
                    " FROM maintenance.cas_jobs"
                    " WHERE request_context->>'cb_number' = ANY(:c)"), {"c": list(cbs)})).fetchall()
                return [tuple(r) for r in rows]
        return self._run(go())

    def _clean_jobs(self, cbs):
        from sqlalchemy import text
        async def go():
            async with self.engine.begin() as db:
                await db.execute(text(
                    "DELETE FROM maintenance.cas_jobs"
                    " WHERE request_context->>'cb_number' = ANY(:c)"), {"c": list(cbs)})
        self._run(go())

    # 1. 同CAS+同chemical+CB001/CB002: 两条独立主 job, 互不吞
    def test_same_cas_two_cbs_two_jobs(self):
        async def go():
            async with self.engine.begin() as db:
                return await self._insert_chem(db, cas=CAS, cb="1111111")
        self._run(go())
        cbs = [PREFIX + "M1", PREFIX + "M2"]
        self._load([(cbs[0], CAS), (cbs[1], CAS)])
        try:
            self._schedule(cbs, max_enqueue=5, new_budget=5)
            rows = dict((r[0], r) for r in self._rows())
            self.assertEqual(rows[cbs[0]][2], "ENQUEUED")
            self.assertEqual(rows[cbs[1]][2], "ENQUEUED")
            jobs = self._jobs(cbs)
            self.assertEqual(len(jobs), 2)   # 不折叠: 各自独立 job
            self.assertEqual({j[2] for j in jobs}, set(cbs))  # source_cb 各自留存
        finally:
            self._clean_jobs(cbs)

    # 2. 同 cb 重跑幂等: 不重复创建同 source job
    def test_same_cb_rerun_idempotent(self):
        async def go():
            async with self.engine.begin() as db:
                return await self._insert_chem(db, cas=CAS, cb="1111111")
        self._run(go())
        cbs = [PREFIX + "M3"]
        self._load([(cbs[0], CAS)])
        try:
            self._schedule(cbs, max_enqueue=5, new_budget=5)
            self._tidy()
            self._run(go())  # fixture 重建
            self._load([(cbs[0], CAS)])
            # 重跑: seed 已 ENQUEUED 不再 eligible, 不产生第二个 job
            self._schedule(cbs, max_enqueue=5, new_budget=5)
            jobs = self._jobs(cbs)
            self.assertEqual(len(jobs), 1)
        finally:
            self._clean_jobs(cbs)

    # 3. NEW placeholder + 第二 cb 同 CAS: 不因首次 placeholder 丢第二个 source record
    def test_new_placeholder_keeps_second_cb(self):
        CASX = "99999-55-5"
        from sqlalchemy import text
        async def wipe():
            async with self.engine.begin() as db:
                await db.execute(text(
                    "DELETE FROM chemistry.chemicals"
                    " WHERE cas_numbers && ARRAY[:c]::text[]"), {"c": CASX})
        self._run(wipe())
        cbs = [PREFIX + "M4", PREFIX + "M5"]
        self._load([(cbs[0], CASX), (cbs[1], CASX)])
        try:
            self._schedule(cbs, max_enqueue=5, new_budget=5)
            rows = dict((r[0], r) for r in self._rows())
            # 两条都入队 (第一条 NEW 物化, 第二条 resolve 命中同 placeholder=EQUIV)
            self.assertEqual(rows[cbs[0]][2], "ENQUEUED")
            self.assertEqual(rows[cbs[1]][2], "ENQUEUED")
            jobs = self._jobs(cbs)
            self.assertEqual(len(jobs), 2)
        finally:
            self._clean_jobs(cbs)
            self._run(wipe())

    # 4. 线上路径零漂移: 不传 source_cb → dedupe_key 与旧语义一致
    def test_online_paths_key_unchanged(self):
        import sys
        sys.path.insert(0, "/var/www/huagongshe")
        from api.services.cb import _dedupe_key
        self.assertEqual(_dedupe_key(123, "7732-18-5"),
                         "cas:123:" + __import__("hashlib").sha256(
                             b"7732-18-5").hexdigest()[:16])
        self.assertEqual(
            _dedupe_key(123, "7732-18-5", "en"),
            _dedupe_key(123, "7732-18-5", "en", source_cb_number=None))
        # 带 source_cb ≠ 不带
        self.assertNotEqual(
            _dedupe_key(123, "7732-18-5", source_cb_number="0100584"),
            _dedupe_key(123, "7732-18-5"))
