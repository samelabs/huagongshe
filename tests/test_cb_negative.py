"""B-minimal: CB negative observations (absence semantics) 测试矩阵。

不变量:
1. chemical_cb 只承载 positive — 本机制绝不写 last_status='not_found'
2. cas_jobs 只承载 queued/leased/error — 终态 complete 后 DELETE 不变
3. negative observation 无 chemical_id — absorb/rekey 零关联
4. ERROR 永不落 negative
5. key grain 不折叠: cas_locator ≠ locale_variant
6. 详情二连击修复: not_found 不再 enqueue fallback
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault(
    "HGS_DATABASE_URL",
    os.environ.get("TEST_DATABASE_URL",
                   "postgresql+asyncpg://test:test@127.0.0.1:5432/test_hgs"))

DB_URL = None
try:
    from tests.db_gate import test_db_or_skip  # noqa: E402
    DB_URL = test_db_or_skip()
except Exception:  # noqa: BLE001
    DB_URL = None

if DB_URL:
    if not DB_URL.startswith("postgresql+asyncpg://"):
        DB_URL = "postgresql+asyncpg://" + DB_URL.split("://", 1)[1]
    DB_URL = DB_URL.split("?", 1)[0]

RUN = random.randint(0, 65535)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) \
        if False else asyncio.run(coro)


def _cas() -> str:
    return f"{RUN % 10000}-{RUN % 100:02d}-{RUN % 10}"


@unittest.skipUnless(DB_URL, "test db unavailable")
class CbNegativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.pool import NullPool
        cls.engine = create_async_engine(DB_URL, poolclass=NullPool)

    @classmethod
    def tearDownClass(cls):
        _run(cls.engine.dispose())

    def setUp(self):
        from sqlalchemy import text

        async def clean():
            async with self.engine.begin() as db:
                await db.execute(text("""
                    DELETE FROM maintenance.cb_negative_observations
                    WHERE cas_number LIKE :c OR cb_number LIKE :cbp
                """), {"c": f"%{RUN}-%", "cbp": f"{RUN}%"})
                await db.execute(text("""
                    DELETE FROM chemistry.chemicals
                    WHERE preferred_name LIKE :p
                """), {"p": f"ut4-neg-{RUN}-%"})
                await db.execute(text("""
                    DELETE FROM maintenance.cas_jobs
                    WHERE cas_number LIKE :p
                """), {"p": f"%{RUN}%{RUN}%"})

        _run(clean())

    # ---- helpers -------------------------------------------------

    def _q(self, sql, **params):
        from sqlalchemy import text

        async def go():
            async with self.engine.begin() as db:
                rows = (await db.execute(text(sql), params)).mappings().fetchall()
                return [dict(r) for r in rows]

        return _run(go())

    def _neg(self, kind=None):
        rows = self._q("""
            SELECT negative_key, kind, cas_number, cb_number, locale,
                   first_observed_at, observed_at
            FROM maintenance.cb_negative_observations
            WHERE cas_number LIKE :c OR cb_number LIKE :cbp
            ORDER BY negative_key
        """, c=f"%{RUN}-%", cbp=f"{RUN}%")
        return rows if kind is None else [r for r in rows if r["kind"] == kind]

    def _mk_chemical(self, **cols) -> int:
        cols.setdefault("preferred_name", f"ut4-neg-{RUN}-x")
        names = ",".join(cols)
        params = ",".join(f":{k}" for k in cols)
        rows = self._q(
            f"INSERT INTO chemistry.chemicals ({names}) "
            f"VALUES ({params}) RETURNING id", **cols)
        return int(rows[0]["id"])

    def _cas_job(self, chemical_id: int, cas: str, locale: str = "zh-CN",
                 cb_number: str | None = None) -> int:
        digest = hashlib.sha256(cas.encode()).hexdigest()[:16]
        suffix = "" if locale == "zh-CN" else f":{locale}"
        if cb_number:
            suffix = f"{suffix}:cb{cb_number}" if suffix else f":cb{cb_number}"
        rows = self._q("""
            INSERT INTO maintenance.cas_jobs
                (chemical_id, cas_number, priority, dedupe_key, status,
                 request_context)
            VALUES (:cid, :cas, 50, :dk, 'leased',
                    CAST(:ctx AS jsonb))
            RETURNING id
        """, cid=chemical_id, cas=cas,
            dk=f"cas:{chemical_id}:{digest}{suffix}",
            ctx=json.dumps({"reason": "ut4-neg"}))
        return int(rows[0]["id"])

    # ---- 服务函数直测 (1-5, 9-13: 表/函数层) -------------------------

    def test_1_record_cas_locator_shape(self):
        from api.services.cb import record_negative
        cas = f"UT4CBNEG{RUN}-11-1"

        async def go():
            from sqlalchemy.ext.asyncio import AsyncSession
            async with AsyncSession(self.engine) as db:
                ok = await record_negative(db, "cas_locator", cas_number=cas)
                await db.commit()
                return ok

        self.assertTrue(_run(go()))
        rows = self._neg("cas_locator")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["negative_key"], f"cbneg:cas:{cas}")
        self.assertIsNone(rows[0]["cb_number"])
        self.assertIsNone(rows[0]["locale"])
        self.assertIsNotNone(rows[0]["first_observed_at"])

    def test_2_record_locale_variant_shape(self):
        from api.services.cb import record_negative
        cb = f"{RUN}77"

        async def go():
            from sqlalchemy.ext.asyncio import AsyncSession
            async with AsyncSession(self.engine) as db:
                ok = await record_negative(db, "locale_variant",
                                           cb_number=cb, locale="en")
                await db.commit()
                return ok

        self.assertTrue(_run(go()))
        rows = self._neg("locale_variant")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["negative_key"], f"cbneg:locale:{cb}:en")
        self.assertIsNone(rows[0]["cas_number"])

    def test_3_fail_closed_missing_locator(self):
        from api.services.cb import record_negative
        # locale_variant 缺 cb_number → 零记录 (禁止猜)
        # cas_locator 缺 cas → 零记录

        async def go():
            from sqlalchemy.ext.asyncio import AsyncSession
            async with AsyncSession(self.engine) as db:
                a = await record_negative(db, "locale_variant", locale="en")
                b = await record_negative(db, "cas_locator")
                await db.commit()
                return a, b

        self.assertEqual(_run(go()), (False, False))
        self.assertEqual(len(self._neg()), 0)

    def test_4_requery_window_fresh_expired(self):
        from api.services.cb import negative_is_fresh, record_negative
        cas = f"UT4CBNEG{RUN}-22-2"

        async def go():
            from sqlalchemy import text
            from sqlalchemy.ext.asyncio import AsyncSession
            async with AsyncSession(self.engine) as db:
                await record_negative(db, "cas_locator", cas_number=cas)
                await db.commit()
            async with AsyncSession(self.engine) as db:
                fresh_now = await negative_is_fresh(
                    db, "cas_locator", cas_number=cas)
                # aged 200d > 180d 窗 → expired
                await db.execute(text("""
                    UPDATE maintenance.cb_negative_observations
                    SET observed_at = now() - interval '200 days'
                    WHERE negative_key = :k
                """), {"k": f"cbneg:cas:{cas}"})
                await db.commit()
            async with AsyncSession(self.engine) as db:
                fresh_old = await negative_is_fresh(
                    db, "cas_locator", cas_number=cas)
            return fresh_now, fresh_old

        self.assertEqual(_run(go()), (True, False))

    def test_5_repeat_observation_keeps_first(self):
        from api.services.cb import record_negative
        cas = f"UT4CBNEG{RUN}-33-3"

        async def go():
            from sqlalchemy import text
            from sqlalchemy.ext.asyncio import AsyncSession
            async with AsyncSession(self.engine) as db:
                await record_negative(db, "cas_locator", cas_number=cas)
                await db.execute(text("""
                    UPDATE maintenance.cb_negative_observations
                    SET first_observed_at = now() - interval '100 days',
                        observed_at = now() - interval '100 days'
                    WHERE negative_key = :k
                """), {"k": f"cbneg:cas:{cas}"})
                await db.commit()
            async with AsyncSession(self.engine) as db:
                await record_negative(db, "cas_locator", cas_number=cas)
                await db.commit()

        _run(go())
        rows = self._neg("cas_locator")
        self.assertEqual(len(rows), 1)
        from datetime import datetime, timezone
        first = rows[0]["first_observed_at"]
        observed = rows[0]["observed_at"]
        self.assertGreater(
            (observed - first).total_seconds(), 99 * 86400)
        self.assertLess(
            (datetime.now(timezone.utc) - observed).total_seconds(), 300)

    def test_6_clear_negative_on_ok(self):
        from api.services.cb import clear_negative, record_negative
        cas = f"UT4CBNEG{RUN}-44-4"
        cb = f"{RUN}88"

        async def go():
            from sqlalchemy.ext.asyncio import AsyncSession
            async with AsyncSession(self.engine) as db:
                await record_negative(db, "cas_locator", cas_number=cas)
                await record_negative(db, "locale_variant",
                                      cb_number=cb, locale="ja")
                await db.commit()
            async with AsyncSession(self.engine) as db:
                await clear_negative(db, "cas_locator", cas_number=cas)
                await clear_negative(db, "locale_variant", cb_number=cb,
                                     locale="ja")
                await db.commit()

        _run(go())
        self.assertEqual(len(self._neg()), 0)


    # ---- 端到端链 (真 cas_complete_job 端点) --------------------------

    LEASE_TOKEN = "s4lease-tokens4lease-tokens4lease"

    def _mk_job(self, chemical_id: int, cas: str) -> int:
        import uuid
        from api.services.workqueue import lease_hash

        digest = hashlib.sha256(cas.encode()).hexdigest()[:16]
        rows = self._q("""
            INSERT INTO maintenance.cas_jobs
                (chemical_id, cas_number, dedupe_key, priority, status,
                 lease_owner, lease_token_hash, lease_expires_at,
                 request_context)
            VALUES (:c, :cas, :dk, 50, 'leased', :w, CAST(:h AS bytea),
                    now() + interval '10 min', CAST(:ctx AS jsonb))
            RETURNING id
        """, c=chemical_id, cas=cas,
            dk=f"cas:{chemical_id}:{digest}",
            w=f"ut4negw{RUN}", h=lease_hash(self.LEASE_TOKEN),
            ctx=json.dumps({"reason": "ut4-neg"}))
        return int(rows[0]["id"])

    def _complete(self, job_id: int, result: dict) -> dict:
        from sqlalchemy.ext.asyncio import AsyncSession
        from api.workapi import cas_complete_job, WorkerContext
        from api.schemas.workapi import CasCompleteBody

        async def go():
            async with AsyncSession(self.engine) as session:
                return await cas_complete_job(
                    CasCompleteBody(job_id=job_id, lease_token=self.LEASE_TOKEN,
                                    result=result),
                    db=session,
                    worker=WorkerContext(worker_id=f"ut4negw{RUN}",
                                         max_lease_jobs=10))

        try:
            return _run(go())
        except Exception as exc:  # endpoint 正常 422/500 语义由用例断言
            return {"__raised__": str(exc)}

    def _job_alive(self, job_id: int) -> bool:
        return len(self._q(
            "SELECT 1 AS x FROM maintenance.cas_jobs WHERE id=:i",
            i=job_id)) == 1

    def _cb_rows_for(self, chemical_id: int) -> list[dict]:
        return self._q("""
            SELECT last_status, locale FROM chemistry.chemical_cb
            WHERE chemical_id=:c
        """, c=chemical_id)

    def test_7_worker_cas_not_found_chain(self):
        """矩阵1: CAS worker not_found → cas negative row + job DELETE
        + chemical_cb 零 not_found row。"""
        cas = f"{RUN}-01-{RUN % 10}"
        cid = self._mk_chemical(cas_numbers=[cas])
        jid = self._mk_job(cid, cas)
        resp = self._complete(jid, {
            "status": "not_found", "entry": None, "suppliers": []})
        self.assertEqual(resp.get("status"), "not_found")
        self.assertFalse(self._job_alive(jid), "job 必须 DELETE")
        negs = self._neg("cas_locator")
        self.assertEqual(len(negs), 1)
        self.assertEqual(negs[0]["cas_number"], cas)
        # chemical_cb 零 not_found row (不变量1)
        nf = self._q("""
            SELECT count(*) AS n FROM chemistry.chemical_cb
            WHERE last_status='not_found' AND chemical_id=:c
        """, c=cid)
        self.assertEqual(nf[0]["n"], 0)
        self.assertEqual(self._cb_rows_for(cid), [])

    def test_8_search_negative_zero_enqueue(self):
        """矩阵3: fresh cas negative → cas_search_state miss, 连续 search
        零新 job。"""
        from api.services.cb import cas_search_state
        cas = f"{RUN}-02-{RUN % 10}"
        cid = self._mk_chemical(cas_numbers=[cas])

        async def go():
            from sqlalchemy.ext.asyncio import AsyncSession
            async with AsyncSession(self.engine) as db:
                # fresh negative (窗内)
                await record_negative(db, "cas_locator", cas_number=cas)
                await db.commit()
            async with AsyncSession(self.engine) as db:
                states = [await cas_search_state(db, cas) for _ in range(10)]
            return states

        from api.services.cb import record_negative
        states = _run(go())
        self.assertEqual(set(states), {"miss"}, "fresh negative 必须 miss")
        jobs = self._q("""
            SELECT count(*) AS n FROM maintenance.cas_jobs WHERE cas_number=:c
        """, c=cas)
        self.assertEqual(jobs[0]["n"], 0, "10 次 search 零新 job")

    def test_9_expired_negative_requery(self):
        """矩阵4: expired → 允许 requery (cas_search_state 照常入列)。"""
        from api.services.cb import cas_search_state, record_negative
        cas = f"{RUN}-03-{RUN % 10}"
        cid = self._mk_chemical(cas_numbers=[cas])

        async def go():
            from sqlalchemy import text
            from sqlalchemy.ext.asyncio import AsyncSession
            async with AsyncSession(self.engine) as db:
                await record_negative(db, "cas_locator", cas_number=cas)
                await db.execute(text("""
                    UPDATE maintenance.cb_negative_observations
                    SET observed_at = now() - interval '400 days'
                    WHERE negative_key = :k
                """), {"k": f"cbneg:cas:{cas}"})
                await db.commit()
            async with AsyncSession(self.engine) as db:
                return await cas_search_state(db, cas)

        state = _run(go())
        self.assertEqual(state, "pending", "expired 允许 requery 入列")

    def test_10_locale_not_found_chain_and_dispatch_gate(self):
        """矩阵6+7: locale not_found → (cb,locale) negative + job 删除;
        zh complete 再派 locale: fresh 不 enqueue / expired enqueue。"""
        cas = f"{RUN}-04-{RUN % 10}"
        cb = f"{RUN}99"
        cid = self._mk_chemical(cas_numbers=[cas])
        jid = self._mk_job(cid, cas)
        resp = self._complete(jid, {
            "status": "not_found", "entry": None, "suppliers": [],
            "locale": "en", "cb_number": cb})
        self.assertEqual(resp.get("status"), "not_found")
        self.assertFalse(self._job_alive(jid))
        negs = self._neg("locale_variant")
        self.assertEqual(len(negs), 1)
        self.assertEqual(negs[0]["negative_key"], f"cbneg:locale:{cb}:en")
        nf = self._q("""
            SELECT count(*) AS n FROM chemistry.chemical_cb
            WHERE last_status='not_found'
        """)
        self.assertEqual(nf[0]["n"], 0, "矩阵13: 全表零 not_found 写入")

        # zh complete → 派发 gate: fresh en negative → 不派 en, 派 ja
        jid2 = self._mk_job(cid, cas)
        self._complete(jid2, {
            "status": "ok", "entry": {
                "props": [{"key": "smiles", "text": "CCO"}],
                "identity": {"en": "UT", "formula": "C2H6O", "mw": 46.07}},
            "suppliers": [], "cb_number": cb})
        en_jobs = self._q("""
            SELECT count(*) AS n FROM maintenance.cas_jobs
            WHERE cas_number=:c AND request_context->>'locale' = 'en'
        """, c=cas)
        ja_jobs = self._q("""
            SELECT count(*) AS n FROM maintenance.cas_jobs
            WHERE cas_number=:c AND request_context->>'locale' = 'ja'
        """, c=cas)
        self.assertEqual(en_jobs[0]["n"], 0, "fresh en negative 不派发")
        self.assertEqual(ja_jobs[0]["n"], 1, "无 negative 的 ja 正常派发")

    def test_11_locale_ok_clears_negative(self):
        """矩阵8: locale 后续 OK → locale negative 删除。"""
        cas = f"{RUN}-05-{RUN % 10}"
        cb = f"{RUN}77"
        cid = self._mk_chemical(cas_numbers=[cas])
        jid = self._mk_job(cid, cas)
        self._complete(jid, {
            "status": "not_found", "entry": None, "suppliers": [],
            "locale": "ko", "cb_number": cb})
        self.assertEqual(len(self._neg("locale_variant")), 1)
        # 同 (cb, locale) 后续 ok → negative 清除 (直接走 complete ok 链)
        jid2 = self._mk_job(cid, cas)
        self._complete(jid2, {
            "status": "ok", "entry": {
                "props": [{"key": "smiles", "text": "CCO"}],
                "identity": {"en": "UT", "formula": "C2H6O", "mw": 46.07}},
            "suppliers": [], "locale": "ko", "cb_number": cb})
        self.assertEqual(len(self._neg("locale_variant")), 0,
                         "ok 后同事务清除 locale negative")

    def test_12_cas_ok_clears_negative(self):
        """矩阵5: CAS 后续 OK → positive 正常写 + cas negative 同事务删。"""
        cas = f"{RUN}-06-{RUN % 10}"
        cid = self._mk_chemical(cas_numbers=[cas])
        jid = self._mk_job(cid, cas)
        self._complete(jid, {
            "status": "not_found", "entry": None, "suppliers": []})
        self.assertEqual(len(self._neg("cas_locator")), 1)
        jid2 = self._mk_job(cid, cas)
        resp = self._complete(jid2, {
            "status": "ok", "entry": {
                "props": [{"key": "smiles", "text": "CCO"}],
                "identity": {"en": "UT", "formula": "C2H6O", "mw": 46.07}},
            "suppliers": []})
        self.assertEqual(resp.get("status"), "ok")
        self.assertEqual(len(self._neg("cas_locator")), 0)
        self.assertEqual(len(self._cb_rows_for(cid)), 1)
        self.assertEqual(self._cb_rows_for(cid)[0]["last_status"], "ok")

    def test_13_no_cb_number_locale_fail_closed(self):
        """矩阵9: locale not_found 但无明确 cb_number → 零 negative。"""
        cas = f"{RUN}-07-{RUN % 10}"
        cid = self._mk_chemical(cas_numbers=[cas])
        jid = self._mk_job(cid, cas)
        self._complete(jid, {
            "status": "not_found", "entry": None, "suppliers": [],
            "locale": "de"})  # 无 cb_number
        self.assertEqual(len(self._neg()), 0, "fail closed 零记录")

    def test_14_error_never_negative(self):
        """矩阵11: ERROR → cas_jobs error 契约原样, 零 negative。"""
        cas = f"{RUN}-08-{RUN % 10}"
        cid = self._mk_chemical(cas_numbers=[cas])
        jid = self._mk_job(cid, cas)
        from api.workapi import cas_error_job
        from api.schemas.workapi import ErrorBody
        from sqlalchemy.ext.asyncio import AsyncSession

        async def go():
            async with AsyncSession(self.engine) as session:
                return await cas_error_job(
                    ErrorBody(job_id=jid, lease_token=self.LEASE_TOKEN,
                              error_code="cb_timeout", error_detail="ut"),
                    db=session,
                    worker=type("W", (), {"worker_id": f"ut4negw{RUN}"})())

        _run(go())
        rows = self._q(
            "SELECT status,last_error_code FROM maintenance.cas_jobs WHERE id=:i",
            i=jid)
        self.assertEqual(rows[0]["status"], "error")
        self.assertEqual(rows[0]["last_error_code"], "cb_timeout")
        self.assertEqual(len(self._neg()), 0)


    def test_15_unbound_ambiguous_cas_not_found_chain(self):
        """远端验收漏口修复: 真实 AMBIGUOUS 链的 unbound job
        (chemical_id=NULL) 明确 not_found → 同事务记 cas_locator
        negative + job DELETE。真链: 双行同 CAS → resolve AMBIGUOUS
        → enqueue_cas_search_fetch → NULL job → 真 complete。"""
        import string
        from sqlalchemy.ext.asyncio import AsyncSession
        from api.services.cb import cas_search_state, enqueue_cas_search_fetch
        from api.services.identity import resolve_chemical

        cas = f"{RUN}-90-{RUN % 10}"
        # 两条共享同 CAS (无 cid/ik/mol → 无结构判据) → resolver AMBIGUOUS
        a = self._mk_chemical(preferred_name=f"ut4-neg-{RUN}-a",
                              cas_numbers=[cas])
        b = self._mk_chemical(preferred_name=f"ut4-neg-{RUN}-b",
                              cas_numbers=[cas])

        async def go():
            async with AsyncSession(self.engine) as db:
                res = await resolve_chemical(db, cas=cas)
                if res.status != "AMBIGUOUS":
                    return ("resolve", res.status)
                enq, rstatus, cid = await enqueue_cas_search_fetch(
                    db, cas_number=cas)
                await db.commit()
                return ("ok", enq, rstatus, cid)

        r = _run(go())
        self.assertEqual(r[0], "ok", f"resolver 状态: {r}")
        _, enq, rstatus, cid = r
        self.assertTrue(enq)
        self.assertEqual(rstatus, "AMBIGUOUS")
        self.assertIsNone(cid, "AMBIGUOUS 不建行不猜行")

        jobs = self._q("""
            SELECT id, chemical_id FROM maintenance.cas_jobs
            WHERE cas_number=:c
        """, c=cas)
        self.assertEqual(len(jobs), 1)
        self.assertIsNone(jobs[0]["chemical_id"], "unbound job chemical_id=NULL")
        jid = int(jobs[0]["id"])

        # worker 租约转换 (真实 lease 端点等价步骤, 非 INSERT NULL job)
        from api.services.workqueue import lease_hash
        self.assertEqual(len(self._q("""
            UPDATE maintenance.cas_jobs
            SET status='leased', lease_owner=:w,
                lease_token_hash=CAST(:h AS bytea),
                lease_expires_at=now()+interval '10 min'
            WHERE id=:i RETURNING id AS x
        """, w=f"ut4negw{RUN}", h=lease_hash(self.LEASE_TOKEN), i=jid)), 1)

        # 真 complete NOT_FOUND (端点直调, 不手工 INSERT NULL job)
        resp = self._complete(jid, {
            "status": "not_found", "entry": None, "suppliers": []})
        self.assertEqual(resp.get("status"), "not_found")
        self.assertTrue(resp.get("standalone"))

        # 断言组: negative 恰1 + key 正确 + job 删 + 双行原样 + 零redirect
        # + 零merge_log + chemical_cb 零not_found + fresh窗内不再新job
        negs = self._neg("cas_locator")
        self.assertEqual(len(negs), 1)
        self.assertEqual(negs[0]["negative_key"], f"cbneg:cas:{cas}")
        self.assertFalse(self._job_alive(jid))
        self.assertEqual(len(self._q(
            "SELECT 1 AS x FROM chemistry.chemicals WHERE id=:i", i=a)), 1)
        self.assertEqual(len(self._q(
            "SELECT 1 AS x FROM chemistry.chemicals WHERE id=:i", i=b)), 1)
        redirects = self._q("""
            SELECT count(*) AS n FROM maintenance.chemical_identity_redirect
            WHERE old_chemical_id IN (:a, :b)
        """, a=a, b=b)
        self.assertEqual(redirects[0]["n"], 0)
        merges = self._q("""
            SELECT count(*) AS n FROM maintenance.identity_merge_log
            WHERE source_id IN (:a, :b) OR target_id IN (:a, :b)
        """, a=a, b=b)
        self.assertEqual(merges[0]["n"], 0)
        nf = self._q("""
            SELECT count(*) AS n FROM chemistry.chemical_cb
            WHERE chemical_id IN (:a, :b) AND last_status='not_found'
        """, a=a, b=b)
        self.assertEqual(nf[0]["n"], 0)

        async def search10():
            async with AsyncSession(self.engine) as db:
                return [await cas_search_state(db, cas) for _ in range(10)]

        states = _run(search10())
        self.assertEqual(set(states), {"miss"},
                         "fresh negative 窗内 10 次搜索不再产生新 job")
        jobs2 = self._q("""
            SELECT count(*) AS n FROM maintenance.cas_jobs
            WHERE cas_number=:c
        """, c=cas)
        self.assertEqual(jobs2[0]["n"], 0)


if __name__ == "__main__":
    unittest.main()
