"""§4 CB callback survivor contract 集成测试。

契约: cas_complete_job relocation 路径必须使用 absorb() 返回的真实
survivor_id, 不得用 res.chemical_id(target 入参)预判哪一行活。
survivor selection 是 absorb/_survivor_pick 内部职权(mol 优先 → cid
→ cb → id 小)。

覆盖四场景:
1 target 胜出: absorb 返回 target, 后续落 target;
2 source(job 行) 胜出(survivor inversion, 关键): res.chemical_id 被删,
  callback 返回值/structure fill/chemical_cb/redirect 全落 survivor,
  零写已删行;
3 MergeBlockedError: 两行保留, 零 destructive merge, 后续既有行为保持;
4 callback transaction failure: absorb 后续异常整体 rollback 零半 merge。

真链不打桩: cas_complete_job + verified_cas_lease + resolve_chemical +
absorb + apply_structure_fill + upsert_externals 全走生产函数,
test_hgs 经 db_gate。
"""

from __future__ import annotations

import asyncio
import os
import random
import string
import unittest
import uuid

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
P = f"ut4cb{RUN}:"
# mol 列为 cartridge mol 类型: mol_in 走 SMILES 解析('CCO'::mol ✓,
# V2000 molblock 反而被当 SMILES 拒) — 夹具用合法 SMILES。
MIN_MOL = "CCO"
LEASE_TOKEN = "s4lease-tokens4lease-tokens4lease"


def _run(coro):
    return asyncio.run(coro)


def _ik(tag: str) -> str:
    return (f"{''.join(random.choices(string.ascii_uppercase, k=6))}{RUN % 1000000:08X}AB"
            f"CD{tag[:3].upper().ljust(3, 'X')}-{tag.ljust(10, 'X')[:10]}-A")[:27]


def _entry(ik: str) -> dict:
    """生产 schema: resolve_structure._props_field 只认 entry["props"] 数组
    (canonical 键 smiles/inchikey); 平铺 dict 不是生产形态。identity 块
    仅为贴近真实 CB entry, relocation 决定性字段是 props。"""
    return {
        "props": [
            {"key": "smiles", "text": "CCO"},
            {"key": "inchikey", "text": ik},
        ],
        "identity": {
            "en": "UT chemical",
            "formula": "C2H6O",
            "mw": 46.07,
        },
    }


@unittest.skipUnless(DB_URL, "需要 PG 测试库")
class CbSurvivorContractTests(unittest.TestCase):
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
                await db.execute(text(
                    "DELETE FROM maintenance.cas_jobs WHERE cas_number LIKE :p"),
                    {"p": f"{RUN}-%"})
                await db.execute(text(
                    "DELETE FROM chemistry.chemicals WHERE preferred_name LIKE :p"),
                    {"p": f"ut4cb-{RUN}-%"})
        _run(clean())

    # ---- helpers -------------------------------------------------

    def _mk_chem(self, cols: dict) -> int:
        from sqlalchemy import text
        names = ",".join(cols)
        params = ",".join(f":{k}" for k in cols)

        async def go():
            async with self.engine.begin() as db:
                return int((await db.execute(text(
                    f"INSERT INTO chemistry.chemicals ({names}) "
                    f"VALUES ({params}) RETURNING id"), cols)).scalar())
        return _run(go())

    def _mk_cas_job(self, chemical_id: int, cas: str) -> int:
        from sqlalchemy import text
        from api.services.workqueue import lease_hash

        async def go():
            async with self.engine.begin() as db:
                return int((await db.execute(text("""
                    INSERT INTO maintenance.cas_jobs
                        (chemical_id, cas_number, dedupe_key, priority,
                         status, lease_owner, lease_token_hash, lease_expires_at)
                    VALUES (:c, :cas, :dk, 50, 'leased', :w, :h,
                            now() + interval '10 min')
                    RETURNING id
                """), {"c": chemical_id, "cas": cas,
                       "dk": f"ut4:{uuid.uuid4().hex}", "w": P + "w1",
                       "h": lease_hash(LEASE_TOKEN)})).scalar())
        return _run(go())

    def _complete(self, job_id: int, result: dict) -> dict:
        from sqlalchemy.ext.asyncio import AsyncSession
        from api.workapi import cas_complete_job, WorkerContext
        from api.schemas.workapi import CasCompleteBody

        async def go():
            async with AsyncSession(self.engine) as session:
                return await cas_complete_job(
                    CasCompleteBody(job_id=job_id, lease_token=LEASE_TOKEN,
                                    result=result),
                    db=session,
                    worker=WorkerContext(worker_id=P + "w1", max_lease_jobs=10))
        return _run(go())

    def _alive(self, row_id: int) -> bool:
        from sqlalchemy import text

        async def go():
            async with self.engine.begin() as db:
                return (await db.execute(text(
                    "SELECT count(*) FROM chemistry.chemicals WHERE id=:i"),
                    {"i": row_id})).scalar()
        return _run(go()) == 1

    def _redirect_target(self, old_id: int) -> int | None:
        from sqlalchemy import text

        async def go():
            async with self.engine.begin() as db:
                return (await db.execute(text(
                    "SELECT canonical_chemical_id FROM "
                    "maintenance.chemical_identity_redirect "
                    "WHERE old_chemical_id=:o"), {"o": old_id})).scalar()
        return _run(go())

    def _cb_rows(self, chemical_id: int) -> int:
        from sqlalchemy import text

        async def go():
            async with self.engine.begin() as db:
                return (await db.execute(text(
                    "SELECT count(*) FROM chemistry.chemical_cb "
                    "WHERE chemical_id=:c"), {"c": chemical_id})).scalar()
        return _run(go())

    def _struct(self, chemical_id: int):
        from sqlalchemy import text

        async def go():
            async with self.engine.begin() as db:
                return (await db.execute(text(
                    "SELECT inchikey,smiles FROM chemistry.chemicals "
                    "WHERE id=:c"), {"c": chemical_id})).fetchone()
        return _run(go())

    def _ok_result(self, ik: str, cb_number: str) -> dict:
        return {"status": "ok", "entry": _entry(ik), "suppliers": [],
                "cb_number": cb_number, "locale": "zh-CN"}

    # ---- 1: target 胜出 -------------------------------------------

    def test_1_target_wins_followups_land_on_target(self):
        """job 行无结构, target 行有 mol → _survivor_pick 选 target。
        后续 structure/externals 必须落 target。"""
        ik = _ik("TGTWINAAAX")
        shared_cid = RUN * 10 + 1
        job_row = self._mk_chem({"preferred_name": f"ut4cb-{RUN}-1job",
                                 "pubchem_cid": shared_cid})
        tgt_row = self._mk_chem({"preferred_name": f"ut4cb-{RUN}-1tgt",
                                 "pubchem_cid": shared_cid,
                                 "inchikey": ik, "mol": MIN_MOL})
        cas = f"{RUN}-1-77-7"
        jid = self._mk_cas_job(job_row, cas)
        resp = self._complete(jid, self._ok_result(ik, str(RUN)))
        # can_merge: 两行 same CID → 放行; survivor=mol 侧(tgt)
        self.assertEqual(resp["chemical_id"], tgt_row,
                         "absorb 返回 survivor(target), 后续全落 target")
        self.assertFalse(self._alive(job_row), "job 行被吸收")
        self.assertTrue(self._alive(tgt_row))
        self.assertEqual(self._struct(tgt_row)[0], ik, "structure fill 落 survivor")
        self.assertGreaterEqual(self._cb_rows(tgt_row), 1, "externals 落 survivor")
        self.assertEqual(self._redirect_target(job_row), tgt_row,
                         "redirect old→survivor 正确")

    # ---- 2: source(job 行) 胜出 — survivor inversion 关键 ----------

    def test_2_source_wins_inversion_uses_absorb_return(self):
        """真正 survivor inversion: job 行(id 小, CID+mol, 无 IK),
        target 行(id 大, CID+mol+incoming IK)。
        resolve_chemical(IK) 命中 target → absorb(source=job, target=tgt)
        → same-CID gate 放行 → 两侧 mol/CID/cb score 全同 → id 小 job 胜出
        → survivor=job, target 被删。
        旧代码 chemical_id=res.chemical_id(target) → 写已删行;
        修复后必须用 absorb 返回值。"""
        ik = _ik("SRCWINAAAX")
        shared_cid = RUN * 10 + 2
        # job/source: 先建(id 小), CID+mol, IK=NULL — resolve 不会命中它
        job_row = self._mk_chem({"preferred_name": f"ut4cb-{RUN}-2job",
                                 "pubchem_cid": shared_cid,
                                 "inchikey": None, "cb_number": None,
                                 "mol": MIN_MOL})
        # target/res: 后建(id 大), CID+mol+incoming IK — resolve 命中它
        tgt_row = self._mk_chem({"preferred_name": f"ut4cb-{RUN}-2tgt",
                                 "pubchem_cid": shared_cid,
                                 "inchikey": ik, "cb_number": None,
                                 "mol": MIN_MOL})
        self.assertLess(job_row, tgt_row, "inversion 前提: job 行 id 较小")
        cas = f"{RUN}-2-88-8"
        jid = self._mk_cas_job(job_row, cas)
        resp = self._complete(jid, self._ok_result(ik, str(RUN)))
        self.assertEqual(resp["chemical_id"], job_row,
                         "callback 必须返回 absorb 的真实 survivor(job 行)")
        self.assertTrue(self._alive(job_row), "survivor(job 行)存活")
        self.assertFalse(self._alive(tgt_row), "res.chemical_id 行被吸收删除")
        self.assertEqual(self._struct(job_row)[0], ik,
                         "structure fill 落 survivor")
        self.assertGreaterEqual(self._cb_rows(job_row), 1,
                                "chemical_cb 落 survivor")
        self.assertEqual(self._redirect_target(tgt_row), job_row,
                         "redirect old(target)→survivor(job 行)正确")
        # merge_log survivor/absorbed 关系正确
        from sqlalchemy import text

        async def mlog():
            async with self.engine.begin() as db:
                r = await db.execute(text(
                    "SELECT source_id,target_id FROM "
                    "maintenance.identity_merge_log "
                    "WHERE (source_id=:s AND target_id=:t) "
                    "   OR (source_id=:t AND target_id=:s)"),
                    {"s": job_row, "t": tgt_row})
                return r.fetchall()
        self.assertEqual(_run(mlog()), [(tgt_row, job_row)],
                         "merge_log 契约: source=absorbed(target被删行), "
                         "target=survivor(job行) — identity.py:506 写入口径")
        # 已删除 target 无任何后续引用(子表/任务)
        async def no_refs():
            async with self.engine.begin() as db:
                cb = (await db.execute(text(
                    "SELECT count(*) FROM chemistry.chemical_cb "
                    "WHERE chemical_id=:t"), {"t": tgt_row})).scalar()
                jobs = (await db.execute(text(
                    "SELECT count(*) FROM maintenance.cas_jobs "
                    "WHERE chemical_id=:t"), {"t": tgt_row})).scalar()
                return int(cb), int(jobs)
        cb_n, job_n = _run(no_refs())
        self.assertEqual((cb_n, job_n), (0, 0),
                         "已删除 target 零后续写入")
        # job 正常出表(原 job 行的任务)
        async def job_out():
            async with self.engine.begin() as db:
                return int((await db.execute(text(
                    "SELECT count(*) FROM maintenance.cas_jobs WHERE id=:j"),
                    {"j": jid})).scalar())
        self.assertEqual(_run(job_out()), 0, "job 正常出表")

    # ---- 3: MergeBlockedError fail-closed --------------------------

    def test_3_merge_blocked_both_rows_kept(self):
        """两行无 CID entity proof(仅 IK 无 CID) → gate BLOCK,
        两行保留, 零 destructive merge, 回补仍走既有落子表行为。"""
        ik = _ik("BLOCKAAAX")
        job_row = self._mk_chem({"preferred_name": f"ut4cb-{RUN}-3job",
                                 "inchikey": ik})
        other_row = self._mk_chem({"preferred_name": f"ut4cb-{RUN}-3oth",
                                   "inchikey": ik, "mol": MIN_MOL})
        cas = f"{RUN}-3-99-9"
        jid = self._mk_cas_job(job_row, cas)
        resp = self._complete(jid, self._ok_result(ik, str(RUN)))
        self.assertTrue(self._alive(job_row), "BLOCK 时 job 行保留")
        self.assertTrue(self._alive(other_row), "BLOCK 时另一行保留")
        self.assertEqual(resp["chemical_id"], job_row,
                         "BLOCK 时回补落 job 行(既有行为)")
        self.assertGreaterEqual(self._cb_rows(job_row), 1,
                                "BLOCK 不中断回补: externals 落子表")
        self.assertIsNone(self._redirect_target(job_row),
                          "零 destructive merge → 零 redirect")

    # ---- 4: transaction failure 整体 rollback -----------------------

    def test_4_post_absorb_failure_rolls_back_whole_merge(self):
        """absorb 成功后 upsert_externals 抛非 ValueError 异常 →
        整事务 rollback: 无半 merge(两行均存活, 零 redirect, job 行未删)。"""
        ik = _ik("ROLLBAAAX")
        shared_cid = RUN * 10 + 4
        job_row = self._mk_chem({"preferred_name": f"ut4cb-{RUN}-4job",
                                 "pubchem_cid": shared_cid})
        tgt_row = self._mk_chem({"preferred_name": f"ut4cb-{RUN}-4tgt",
                                 "pubchem_cid": shared_cid, "mol": MIN_MOL,
                                 "inchikey": ik})
        cas = f"{RUN}-4-10-0"
        jid = self._mk_cas_job(job_row, cas)
        from api.services import cb as cbmod
        orig = cbmod.upsert_externals

        async def boom(db, **kw):
            raise RuntimeError("injected post-absorb failure")

        async def go():
            cbmod.upsert_externals = boom
            try:
                self._complete(jid, self._ok_result(ik, str(RUN)))
                return None
            finally:
                cbmod.upsert_externals = orig
        with self.assertRaises(RuntimeError):
            _run(go())
        self.assertTrue(self._alive(job_row), "rollback 后 job 行仍存活")
        self.assertTrue(self._alive(tgt_row), "rollback 后 target 行仍存活")
        self.assertIsNone(self._redirect_target(job_row),
                          "零半 merge: 无 redirect 残留")
        from sqlalchemy import text

        async def job_alive():
            async with self.engine.begin() as db:
                return (await db.execute(text(
                    "SELECT count(*) FROM maintenance.cas_jobs WHERE id=:j"),
                    {"j": jid})).scalar()
        self.assertEqual(_run(job_alive()), 1, "job 未出表(整事务回滚)")


if __name__ == "__main__":
    unittest.main()
