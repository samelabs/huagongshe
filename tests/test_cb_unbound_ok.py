"""B-safe: unbound CAS OK callback 的安全绑定 (P1, 2026-09-10)。

authority = resolved chemical_id ∈ callback-time CAS candidate set。
真链: 双/单候选行 → enqueue_cas_search_fetch (AMBIGUOUS→NULL job) →
worker lease → 真 cas_complete_job。不手工伪造 callback 状态。
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

RUN = random.randint(10_000_000, 99_000_000)
LEASE_TOKEN = "s4lease-tokens4lease-tokens4lease"


def _run(coro):
    return asyncio.run(coro)


def _ik(tag: str) -> str:
    """合法 14-10-1 InChIKey, 纯大写字母段(冻结 INCHIKEY_RE ^[A-Z]{14}-
    [A-Z]{10}-[A-Z]$: seg2 不允许数字), RUN+tag 派生保证跨用例唯一。"""
    import hashlib
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    n = int(hashlib.sha256(f"{RUN}-{tag}".encode()).hexdigest(), 16)
    def take(k: int) -> str:
        nonlocal n
        s = ""
        for _ in range(k):
            s += letters[n % 26]
            n //= 26
        return s
    return f"{take(14)}-{take(10)}-A"


def _entry(ik: str | None) -> dict:
    props = [{"key": "smiles", "text": "CCO"}]
    if ik is not None:
        props.append({"key": "inchikey", "text": ik})
    return {
        "props": props,
        "identity": {"en": "UT chemical", "formula": "C2H6O", "mw": 46.07},
    }


@unittest.skipUnless(DB_URL, "需要 PG 测试库")
class CbUnboundOkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault(
            "HGS_DATABASE_URL",
            os.environ.get("TEST_DATABASE_URL",
                           "postgresql+asyncpg://test:test@127.0.0.1:5432/test_hgs"))
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
                    DELETE FROM maintenance.cas_jobs WHERE cas_number LIKE :p
                """), {"p": f"%{RUN}-%"})
                await db.execute(text("""
                    DELETE FROM maintenance.cb_negative_observations
                    WHERE cas_number LIKE :p OR cb_number LIKE :p
                """), {"p": f"%{RUN}%"})
                await db.execute(text("""
                    DELETE FROM chemistry.chemicals WHERE preferred_name LIKE :p
                """), {"p": f"ut4-p1-{RUN}-%"})

        _run(clean())

    # ---- helpers -------------------------------------------------

    def _q(self, sql, **params):
        from sqlalchemy import text

        async def go():
            async with self.engine.begin() as db:
                rows = (await db.execute(text(sql), params)).mappings().fetchall()
                return [dict(r) for r in rows]

        return _run(go())

    def _exec(self, sql, **params):
        from sqlalchemy import text

        async def go():
            async with self.engine.begin() as db:
                await db.execute(text(sql), params)

        return _run(go())

    def _mk_chemical(self, name: str, *, cas: str | None = None,
                     inchikey: str | None = None, mol: str | None = None) -> int:
        cols: dict = {"preferred_name": name}
        if cas:
            cols["cas_numbers"] = [cas] if isinstance(cas, str) else cas
        if inchikey:
            cols["inchikey"] = inchikey
        if mol:
            cols["mol"] = mol
        names = ",".join(cols)
        params = ",".join(f":{k}" for k in cols)
        rows = self._q(
            f"INSERT INTO chemistry.chemicals ({names}) "
            f"VALUES ({params}) RETURNING id", **cols)
        return int(rows[0]["id"])

    def _enqueue_unbound(self, cas: str) -> int:
        """真链: 双候选 → resolve AMBIGUOUS → NULL job(queued) → lease。"""
        from sqlalchemy.ext.asyncio import AsyncSession
        from api.services.cb import enqueue_cas_search_fetch

        async def go():
            async with AsyncSession(self.engine) as db:
                enq, status, cid = await enqueue_cas_search_fetch(
                    db, cas_number=cas)
                await db.commit()
                assert enq and status == "AMBIGUOUS" and cid is None, \
                    f"预期 unbound 入列, got {status}/{cid}"
            from api.services.workqueue import lease_hash
            async with self.engine.begin() as db:
                jid = (await db.execute(text(
                    "SELECT id FROM maintenance.cas_jobs WHERE cas_number=:c"
                ), {"c": cas})).scalar()
                assert jid is not None
                await db.execute(text("""
                    UPDATE maintenance.cas_jobs
                    SET status='leased', lease_owner=:w,
                        lease_token_hash=CAST(:h AS bytea),
                        lease_expires_at=now()+interval '10 min'
                    WHERE id=:i
                """), {"w": f"ut4p1w{RUN}", "h": lease_hash(LEASE_TOKEN),
                       "i": jid})
            return int(jid)

        from sqlalchemy import text
        return _run(go())

    def _complete_ok(self, job_id: int, ik: str | None,
                     cb_number: str | None = None) -> dict:
        from sqlalchemy.ext.asyncio import AsyncSession
        from api.workapi import cas_complete_job, WorkerContext
        from api.schemas.workapi import CasCompleteBody

        async def go():
            async with AsyncSession(self.engine) as session:
                return await cas_complete_job(
                    CasCompleteBody(job_id=job_id, lease_token=LEASE_TOKEN,
                                    result={"status": "ok",
                                            "entry": _entry(ik),
                                            "suppliers": [],
                                            **({"cb_number": cb_number}
                                               if cb_number else {})}),
                    db=session,
                    worker=WorkerContext(worker_id=f"ut4p1w{RUN}",
                                         max_lease_jobs=10))

        try:
            return _run(go())
        except Exception as exc:
            return {"__raised__": str(exc)}

    def _job_count(self, cas: str) -> int:
        return self._q(
            "SELECT count(*) AS n FROM maintenance.cas_jobs WHERE cas_number=:c",
            c=cas)[0]["n"]

    def _cb_owner(self, cas: str) -> list[int]:
        return [r["chemical_id"] for r in self._q("""
            SELECT DISTINCT chemical_id FROM chemistry.chemical_cb
            WHERE cas_number=:c
        """, c=cas)]

    def _neg_cas(self, cas: str) -> int:
        return len(self._q("""
            SELECT 1 AS x FROM maintenance.cb_negative_observations
            WHERE negative_key = :k
        """, k=f"cbneg:cas:{cas}"))

    def _identity_touched(self, *ids: int) -> bool:
        """零 redirect / 零 merge_log 断言用。"""
        r = self._q("""
            SELECT count(*) AS n FROM maintenance.chemical_identity_redirect
            WHERE old_chemical_id = ANY(:ids)
        """, ids=list(ids))[0]["n"]
        m = self._q("""
            SELECT count(*) AS n FROM maintenance.identity_merge_log
            WHERE source_id = ANY(:ids) OR target_id = ANY(:ids)
        """, ids=list(ids))[0]["n"]
        return r == 0 and m == 0

    def _ik_of(self, cid: int) -> str | None:
        return self._q(
            "SELECT inchikey AS i FROM chemistry.chemicals WHERE id=:c",
            c=cid)[0]["i"]

    # ---- T1: two-hit, IK 唯一命中 A → bind A -----------------------

    def test_T1_ik_hits_A_binds_A(self):
        cas = f"{RUN}-11-1"
        ik = _ik("T1")
        a = self._mk_chemical(f"ut4-p1-{RUN}-a", cas=cas,
                              inchikey=ik, mol="CCO")
        b = self._mk_chemical(f"ut4-p1-{RUN}-b", cas=cas)
        jid = self._enqueue_unbound(cas)
        resp = self._complete_ok(jid, ik)
        self.assertEqual(resp.get("status"), "ok")
        self.assertNotIn("standalone", resp, "bind 成功走 bound 汇总")
        self.assertEqual(resp.get("chemical_id"), a, "CB 数据必须落 A")
        self.assertEqual(self._cb_owner(cas), [a])
        self.assertEqual(self._job_count(cas), 0)
        self.assertTrue(self._identity_touched(a, b), "零 redirect/merge")
        self.assertEqual(self._ik_of(b), None, "B 原样")

    def test_T2_ik_hits_B_binds_B(self):
        cas = f"{RUN}-12-2"
        ik = _ik("T2")
        a = self._mk_chemical(f"ut4-p1-{RUN}-a", cas=cas)
        b = self._mk_chemical(f"ut4-p1-{RUN}-b", cas=cas,
                              inchikey=ik, mol="CCO")
        jid = self._enqueue_unbound(cas)
        resp = self._complete_ok(jid, ik)
        self.assertEqual(resp.get("chemical_id"), b)
        self.assertEqual(self._cb_owner(cas), [b])

    def test_T3_ik_no_hit_unresolved(self):
        cas = f"{RUN}-13-3"
        a = self._mk_chemical(f"ut4-p1-{RUN}-a", cas=cas)
        b = self._mk_chemical(f"ut4-p1-{RUN}-b", cas=cas)
        jid = self._enqueue_unbound(cas)
        resp = self._complete_ok(jid, _ik("T3-elsewhere"))
        self.assertTrue(resp.get("standalone"))
        self.assertFalse(resp.get("resolved", True))
        self.assertEqual(self._job_count(cas), 0, "job DELETE")
        self.assertEqual(self._cb_owner(cas), [], "候选零 CB 写")
        self.assertEqual(self._neg_cas(cas), 0, "零 negative")
        self.assertTrue(self._identity_touched(a, b))

    def test_T4_ik_hits_outside_C_rejected(self):
        """集外 C 有同 IK+mol(不带 CAS), 候选 A 有 same IK 但 mol=NULL:
        resolver global-IK 序位会返回 C — 调用方必须拒绝。"""
        cas = f"{RUN}-14-4"
        ik = _ik("T4")
        a = self._mk_chemical(f"ut4-p1-{RUN}-a", cas=cas, inchikey=ik)  # mol NULL
        b = self._mk_chemical(f"ut4-p1-{RUN}-b", cas=cas)
        c = self._mk_chemical(f"ut4-p1-{RUN}-c", inchikey=ik, mol="CCO")  # 集外
        # 实证 resolver 真会返回 C
        from sqlalchemy.ext.asyncio import AsyncSession
        from api.services.identity import resolve_chemical

        async def probe():
            async with AsyncSession(self.engine) as db:
                return await resolve_chemical(db, inchikey=ik, cas=cas,
                                              create=False)

        res = _run(probe())
        self.assertEqual(res.status, "EQUIVALENT")
        self.assertEqual(res.chemical_id, c, "resolver 前置校验: 确实偏航到 C")

        jid = self._enqueue_unbound(cas)
        resp = self._complete_ok(jid, ik)
        self.assertFalse(resp.get("resolved", True), "调用方必须拒绝跨集")
        self.assertEqual(self._cb_owner(cas), [], "A/B 零 CB 写")
        ccb = self._q("""
            SELECT count(*) AS n FROM chemistry.chemical_cb
            WHERE chemical_id=:c
        """, c=c)[0]["n"]
        self.assertEqual(ccb, 0, "C 零 CB 写")
        self.assertEqual(self._job_count(cas), 0)
        self.assertTrue(self._identity_touched(a, b, c))

    def test_T5_single_candidate_ik_mismatch_rejected(self):
        """关键防线: 单候选 A.inchikey != incoming → 即使 resolver
        cas-unique-hit 返回 EQUIVALENT 也拒绝。"""
        cas = f"{RUN}-15-5"
        a_ik = _ik("T5-row")
        in_ik = _ik("T5-incoming")
        a = self._mk_chemical(f"ut4-p1-{RUN}-a", cas=cas,
                              inchikey=a_ik, mol="CCO")
        # enqueue 时双候选(AMBIGUOUS→unbound), callback 前删 B 收敛为单候选
        b = self._mk_chemical(f"ut4-p1-{RUN}-b", cas=cas)
        jid = self._enqueue_unbound(cas)
        self._exec("DELETE FROM chemistry.chemicals WHERE id=:i", i=b)
        resp = self._complete_ok(jid, in_ik)
        self.assertFalse(resp.get("resolved", True))
        self.assertEqual(self._cb_owner(cas), [])
        self.assertEqual(self._ik_of(a), a_ik, "行内 IK 不被覆盖")
        self.assertTrue(self._identity_touched(a))

    def test_T6_single_candidate_null_ik_binds_fills(self):
        cas = f"{RUN}-16-6"
        ik = _ik("T6")
        a = self._mk_chemical(f"ut4-p1-{RUN}-a", cas=cas)  # IK NULL
        # callback-time 收敛场景: enqueue 时双候选(AMBIGUOUS→unbound job),
        # 异步期间 B 被删 → callback 时只剩 A。非手工伪造 callback 状态。
        b = self._mk_chemical(f"ut4-p1-{RUN}-b", cas=cas)
        jid = self._enqueue_unbound(cas)
        self._exec("DELETE FROM chemistry.chemicals WHERE id=:i", i=b)
        resp = self._complete_ok(jid, ik)
        self.assertEqual(resp.get("chemical_id"), a)
        self.assertEqual(self._cb_owner(cas), [a])
        self.assertEqual(self._ik_of(a), ik, "fill incoming valid IK")

    def test_T7_multi_no_ik_unresolved(self):
        cas = f"{RUN}-17-7"
        a = self._mk_chemical(f"ut4-p1-{RUN}-a", cas=cas)
        b = self._mk_chemical(f"ut4-p1-{RUN}-b", cas=cas)
        jid = self._enqueue_unbound(cas)
        resp = self._complete_ok(jid, None)  # 无 IK
        self.assertFalse(resp.get("resolved", True))
        self.assertEqual(self._cb_owner(cas), [])
        self.assertTrue(self._identity_touched(a, b))

    def test_T8_malformed_ik_not_evidence(self):
        cas = f"{RUN}-18-8"
        a = self._mk_chemical(f"ut4-p1-{RUN}-a", cas=cas)
        b = self._mk_chemical(f"ut4-p1-{RUN}-b", cas=cas)
        jid = self._enqueue_unbound(cas)
        bad = "NOT-A-REAL-INCHIKEY!!"  # 非 14-10-1
        resp = self._complete_ok(jid, bad)
        self.assertFalse(resp.get("resolved", True),
                         "malformed IK 当无 IK → multi 无判据 unresolved")
        self.assertEqual(self._cb_owner(cas), [])
        for cid in (a, b):
            self.assertNotEqual(self._ik_of(cid), bad,
                                "malformed IK 不得写入 identity 字段")

    def test_T9_unresolved_ok_clears_negative(self):
        cas = f"{RUN}-19-9"
        a = self._mk_chemical(f"ut4-p1-{RUN}-a", cas=cas)
        b = self._mk_chemical(f"ut4-p1-{RUN}-b", cas=cas)
        # 旧 cas_locator negative (fresh)
        from api.services.cb import record_negative
        from sqlalchemy.ext.asyncio import AsyncSession

        async def seed():
            async with AsyncSession(self.engine) as db:
                await record_negative(db, "cas_locator", cas_number=cas)
                await db.commit()

        _run(seed())
        self.assertEqual(self._neg_cas(cas), 1)
        jid = self._enqueue_unbound(cas)
        resp = self._complete_ok(jid, _ik("T9-none"))  # unresolved OK
        self.assertFalse(resp.get("resolved", True))
        self.assertEqual(self._neg_cas(cas), 0,
                         "OK 但 unresolved 也证明 CAS 存在 → negative 清除")
        self.assertEqual(self._cb_owner(cas), [])

    def test_T10_safe_bind_clears_negative(self):
        cas = f"{RUN}-20-0"
        ik = _ik("T10")
        a = self._mk_chemical(f"ut4-p1-{RUN}-a", cas=cas,
                              inchikey=ik, mol="CCO")
        b = self._mk_chemical(f"ut4-p1-{RUN}-b", cas=cas)
        from api.services.cb import record_negative
        from sqlalchemy.ext.asyncio import AsyncSession

        async def seed():
            async with AsyncSession(self.engine) as db:
                await record_negative(db, "cas_locator", cas_number=cas)
                await db.commit()

        _run(seed())
        jid = self._enqueue_unbound(cas)
        resp = self._complete_ok(jid, ik)
        self.assertEqual(resp.get("chemical_id"), a)
        self.assertEqual(self._neg_cas(cas), 0, "bind 同事务清 negative")
        self.assertEqual(self._cb_owner(cas), [a])

    def test_T11_never_absorb_redirect_merge(self):
        """所有 unbound OK 路径零 absorb/redirect/merge_log(结构性断言):
        T1(bind) + T3(unresolved) 已各自断言 _identity_touched; 此处
        汇总跑两条链再验一次全量零痕。"""
        cas1 = f"{RUN}-21-1"
        ik = _ik("T11")
        a = self._mk_chemical(f"ut4-p1-{RUN}-a", cas=cas1,
                              inchikey=ik, mol="CCO")
        b = self._mk_chemical(f"ut4-p1-{RUN}-b", cas=cas1)
        jid = self._enqueue_unbound(cas1)
        self._complete_ok(jid, ik)
        cas2 = f"{RUN}-22-2"
        c = self._mk_chemical(f"ut4-p1-{RUN}-c", cas=cas2)
        d = self._mk_chemical(f"ut4-p1-{RUN}-d", cas=cas2)
        jid2 = self._enqueue_unbound(cas2)
        self._complete_ok(jid2, _ik("T11-x"))
        self.assertTrue(self._identity_touched(a, b, c, d))


if __name__ == "__main__":
    unittest.main()
