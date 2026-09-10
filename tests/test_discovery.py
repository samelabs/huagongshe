"""§3 MVP PubChem identity discovery 集成测试。

覆盖(立项令 14 项之 1-12, 13/14 由回归矩阵承担):
1 新 reaction IK → 恰一个 discovery job
2 CB NULL→IK → 产生 job
3 CB 已有 IK 重复 callback → 不重复 job
4 同 evidence terminal NOT_FOUND 再 trigger → 不复活
5 evidence A→B → B 可产生新 job
6 A leased 后 evidence 变 B → A complete 为 SUPERSEDED
7 0 CID → NOT_FOUND
8 >1 CID → AMBIGUOUS 绝不 first-hit
9 1 CID → 原子产生 pubchem_jobs
10 handoff 中途异常 → identity 状态与 pubchem_jobs 一起 rollback
11 redirect 后对 survivor 处理
12 全流程 chemicals identity 字段零直接写

真链不打桩: enqueue_discovery / complete_discovery / apply_structure_fill
全部走真实生产函数; 测试库 = db_gate(test_hgs)。
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


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro) \
        if False else asyncio.run(coro)


def _ik(suffix: str) -> str:
    """合法 InChIKey: 27 字符 14-10-1 纯大写字母(跨运行唯一域)。"""
    return (f"{''.join(random.choices(string.ascii_uppercase, k=6))}{RUN % 1000000:08X}AB"
            f"CD{suffix[:3].upper().ljust(3, 'X')}-{suffix.ljust(10, 'X')[:10]}-A")[:27]


@unittest.skipUnless(DB_URL, "需要 PG 测试库")
def _fixture_smiles(run: int) -> str:
    """高熵短 SMILES fixture(ns=disc): 取代卤素/杂原子 3 bits × 链长 6-13,
    hash 编码进多个结构位而非只编码链长 — canonical 后仍高熵差异,
    实际不可耗尽; 20k 抽样 100% 合法。配合 setUp 显式 cleanup(按精确
    smiles 删行), is_new 断言不再依赖同系物长度空间的唯一性。"""
    import hashlib
    n = int(hashlib.sha256(f"disc:{run}".encode()).hexdigest(), 16)
    hal = {0: "", 1: "F", 2: "Cl", 3: "Br", 4: "I", 5: "N", 6: "O", 7: "S"}
    length = 6 + ((n >> 30) & 7)
    parts = ["C"]
    for i in range(1, length):
        sub = hal[(n >> (3 * i)) & 7]
        parts.append(f"({sub})C" if sub else "C")
    return "".join(parts)

class IdentityDiscoveryTests(unittest.TestCase):
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
                    DELETE FROM maintenance.pubchem_identity_jobs
                    WHERE evidence_value LIKE :p
                """), {"p": f"%{RUN:08X}%"})
                await db.execute(text("""
                    DELETE FROM chemistry.chemicals WHERE preferred_name LIKE :p
                """), {"p": f"ut4-{RUN}-%"})
                await db.execute(text("""
                    DELETE FROM chemistry.chemicals WHERE smiles = :s
                """), {"s": _fixture_smiles(RUN)})
        _run(clean())

    # ---- helpers -------------------------------------------------

    def _mk_chemical(self, cols: dict) -> int:
        from sqlalchemy import text
        names = ",".join(cols)
        params = ",".join(f":{k}" for k in cols)
        async def go():
            async with self.engine.begin() as db:
                return int((await db.execute(text(
                    f"INSERT INTO chemistry.chemicals ({names}) VALUES ({params}) RETURNING id"),
                    cols)).scalar())
        return _run(go())

    def _discovery_rows(self, chemical_id: int) -> list[dict]:
        from sqlalchemy import text
        async def go():
            async with self.engine.begin() as db:
                rows = (await db.execute(text("""
                    SELECT id,status,evidence_value,evidence_hash,result
                    FROM maintenance.pubchem_identity_jobs
                    WHERE chemical_id=:c ORDER BY id
                """), {"c": chemical_id})).fetchall()
                return [dict(zip(("id", "status", "ev", "eh", "result"), r)) for r in rows]
        return _run(go())

    def _pubchem_job_for(self, chemical_id: int, cid: int) -> int:
        from sqlalchemy import text
        async def go():
            async with self.engine.begin() as db:
                return int((await db.execute(text(
                    "SELECT count(*) FROM maintenance.pubchem_jobs "
                    "WHERE chemical_id=:c AND query_value=:q"),
                    {"c": chemical_id, "q": str(cid)})).scalar())
        return _run(go())

    def _mk_leased(self, chemical_id: int, ev: str) -> int:
        """直接置 leased 态(模拟 worker 持约, 绕开 lease 端点)。"""
        from sqlalchemy import text
        async def go():
            async with self.engine.begin() as db:
                from api.services.workqueue import lease_hash
                jid = int((await db.execute(text("""
                    INSERT INTO maintenance.pubchem_identity_jobs
                        (chemical_id,evidence_type,evidence_value,evidence_hash,
                         status,priority,dedupe_key,lease_owner,lease_token_hash,
                         lease_expires_at)
                    VALUES (:c,'inchikey',:ev,:eh,'leased',60,:dk,'ut4w',:th,
                            now()+interval '10 min')
                    RETURNING id
                """), {"c": chemical_id, "ev": ev,
                       "eh": __import__("hashlib").sha256(ev.encode()).hexdigest(),
                       "dk": f"disc:{chemical_id}:inchikey:{__import__('hashlib').sha256(ev.encode()).hexdigest()}",
                       "th": lease_hash("t" * 43)})).scalar())
                return jid
        return _run(go())

    def _complete(self, job_id: int, cid_list: list[int]) -> str:
        from api.services.discovery import complete_discovery
        async def go():
            async with self.engine.begin() as db:
                return await complete_discovery(db, job_id=job_id, cid_list=cid_list)
        return _run(go())

    # ---- 1: reaction 新建 IK → 一个 job --------------------------

    def test_1_reaction_insert_creates_single_job(self):
        ik = _ik("REACTIONONE")
        from api.services.discovery import enqueue_discovery
        row_id = self._mk_chemical({"inchikey": ik,
                                    "preferred_name": f"ut4-{RUN}-n1"})
        async def go():
            async with self.engine.begin() as db:
                await enqueue_discovery(db, chemical_id=row_id, inchikey=ik,
                                        request_context={"origin": "reaction_insert"})
                await enqueue_discovery(db, chemical_id=row_id, inchikey=ik)  # 重复触发
        _run(go())
        rows = self._discovery_rows(row_id)
        self.assertEqual(len(rows), 1, "同 evidence 重复触发必须幂等为单 job")
        self.assertEqual(rows[0]["status"], "queued")

    def test_1b_real_reaction_chain_creates_job(self):
        """§3 correction 防回归: 真调 resolve_or_create_chemical() 整链
        (不是直调 enqueue_discovery 却命名为 reaction trigger 的覆盖假象)。
        断言: is_new=True / discovery job 恰 1 条 / status=queued。
        覆盖 0de4d4b 基线上局部 import 缺失被 best-effort 静默吞掉的缺陷
        (reaction 主流程成功但 discovery 永不入队)。"""
        from api.reactions import resolve_or_create_chemical
        # 高熵 fixture(ns=disc) + setUp 精确 cleanup — 不再依赖同系物
        # 长度空间唯一性(历史假红根源)
        smiles = _fixture_smiles(RUN)
        created: dict = {}

        async def go():
            async with self.engine.begin() as db:
                chemical_id, is_new = await resolve_or_create_chemical(db, smiles)
                created["id"], created["is_new"] = chemical_id, is_new

        _run(go())
        self.assertTrue(created["is_new"], "RUN 唯一 SMILES 必须新建行")
        rows = self._discovery_rows(created["id"])
        self.assertEqual(len(rows), 1, "真链 reaction 新建 IK → 恰 1 条 discovery job")
        self.assertEqual(rows[0]["status"], "queued")
        self.assertEqual(rows[0]["ev"], _run(self._ik_of(created["id"])))

    def _ik_of(self, chemical_id: int):
        from sqlalchemy import text
        async def go():
            async with self.engine.begin() as db:
                return (await db.execute(text(
                    "SELECT inchikey FROM chemistry.chemicals WHERE id=:c"
                ), {"c": chemical_id})).scalar()
        return go()

    # ---- 2/3: CB structure fill 触发 ------------------------------

    def _apply_fill(self, chemical_id: int, structure: dict):
        from api.services.cb import apply_structure_fill
        async def go():
            async with self.engine.begin() as db:
                await apply_structure_fill(db, chemical_id, structure)
        _run(go())

    def test_2_cb_fill_null_to_ik_creates_job(self):
        ik = _ik("CBFILLAA")
        cid_ = self._mk_chemical({"preferred_name": f"ut4-{RUN}-n2",
                                  "smiles": "CCO"})
        self._apply_fill(cid_, {"smiles": "CCO", "inchikey": ik, "mol": None})
        rows = self._discovery_rows(cid_)
        self.assertEqual(len(rows), 1, "NULL→IK 必须产生 discovery job")
        self.assertEqual(rows[0]["status"], "queued")

    def test_3_cb_fill_existing_ik_no_new_job(self):
        ik = _ik("CBKEEPAAB")
        cid_ = self._mk_chemical({"preferred_name": f"ut4-{RUN}-n3",
                                  "smiles": "CCO", "inchikey": ik})
        self._apply_fill(cid_, {"smiles": "CCO", "inchikey": ik, "mol": None})
        rows = self._discovery_rows(cid_)
        self.assertEqual(len(rows), 0, "已有 IK(非 NULL→non-NULL)不触发")

    # ---- 4: 终态不复活 -------------------------------------------

    def test_4_terminal_not_found_no_revive(self):
        ik = _ik("NOTFOUNDAA")
        from api.services.discovery import enqueue_discovery
        cid_ = self._mk_chemical({"inchikey": ik,
                                  "preferred_name": f"ut4-{RUN}-n4"})
        jid = self._mk_leased(cid_, ik)
        self.assertEqual(self._complete(jid, []), "not_found")
        async def go():
            async with self.engine.begin() as db:
                await enqueue_discovery(db, chemical_id=cid_, inchikey=ik)
        _run(go())
        rows = self._discovery_rows(cid_)
        self.assertEqual(len(rows), 1, "同 evidence 终态后再 trigger 不复活")
        self.assertEqual(rows[0]["status"], "not_found")

    # ---- 5: evidence A→B 新 job ----------------------------------

    def test_5_new_evidence_new_job(self):
        ik_a = _ik("EVIDAAXAAA")
        ik_b = _ik("EVIDBBXAAA")
        cid_ = self._mk_chemical({"inchikey": ik_a,
                                  "preferred_name": f"ut4-{RUN}-n5"})
        jid = self._mk_leased(cid_, ik_a)
        self.assertEqual(self._complete(jid, []), "not_found")
        # 行 evidence 变 B(模拟后续 re-fill)
        from sqlalchemy import text
        async def upd():
            async with self.engine.begin() as db:
                await db.execute(text(
                    "UPDATE chemistry.chemicals SET inchikey=:ik WHERE id=:id"),
                    {"ik": ik_b, "id": cid_})
        _run(upd())
        from api.services.discovery import enqueue_discovery
        async def go():
            async with self.engine.begin() as db:
                await enqueue_discovery(db, chemical_id=cid_, inchikey=ik_b)
        _run(go())
        rows = self._discovery_rows(cid_)
        self.assertEqual(len(rows), 2, "新 evidence_hash 允许新 job")
        self.assertEqual(rows[1]["status"], "queued")
        self.assertEqual(rows[1]["ev"], ik_b)

    # ---- 6: SUPERSEDED -------------------------------------------

    def test_6_leased_then_evidence_changed_superseded(self):
        ik_a = _ik("SUPERAAXAAA")
        ik_b = _ik("SUPERBBXAAA")
        cid_ = self._mk_chemical({"inchikey": ik_a,
                                  "preferred_name": f"ut4-{RUN}-n6"})
        jid = self._mk_leased(cid_, ik_a)
        # lease 期间行 evidence 变 B
        from sqlalchemy import text
        async def upd():
            async with self.engine.begin() as db:
                await db.execute(text(
                    "UPDATE chemistry.chemicals SET inchikey=:ik WHERE id=:id"),
                    {"ik": ik_b, "id": cid_})
        _run(upd())
        self.assertEqual(self._complete(jid, [RUN * 10 + 6]), "superseded")
        rows = self._discovery_rows(cid_)
        self.assertEqual(rows[0]["status"], "superseded")
        self.assertEqual(self._pubchem_job_for(cid_, RUN * 10 + 6), 0,
                         "superseded 不得 enqueue enrichment")

    # ---- 7: 0 CID → NOT_FOUND ------------------------------------

    def test_7_zero_cid_not_found(self):
        ik = _ik("ZEROCIDAAX")
        cid_ = self._mk_chemical({"inchikey": ik,
                                  "preferred_name": f"ut4-{RUN}-n7"})
        jid = self._mk_leased(cid_, ik)
        self.assertEqual(self._complete(jid, []), "not_found")
        self.assertEqual(self._discovery_rows(cid_)[0]["status"], "not_found")

    # ---- 8: >1 CID → AMBIGUOUS 绝不 first-hit ----------------------

    def test_8_multi_cid_ambiguous_no_first_hit(self):
        ik = _ik("AMBIGAAAX")
        cid_ = self._mk_chemical({"inchikey": ik,
                                  "preferred_name": f"ut4-{RUN}-n8"})
        jid = self._mk_leased(cid_, ik)
        c1, c2 = RUN * 10 + 81, RUN * 10 + 82
        self.assertEqual(self._complete(jid, [c1, c2]), "ambiguous")
        rows = self._discovery_rows(cid_)
        self.assertEqual(rows[0]["status"], "ambiguous")
        self.assertEqual(self._pubchem_job_for(cid_, c1), 0, "绝不 first-hit 入队")
        self.assertEqual(self._pubchem_job_for(cid_, c2), 0)

    # ---- 9: 1 CID → candidate + 原子 pubchem_jobs ------------------

    def test_9_single_cid_candidate_handoff(self):
        ik = _ik("CANDIDAAX")
        cid_ = self._mk_chemical({"inchikey": ik,
                                  "preferred_name": f"ut4-{RUN}-n9"})
        jid = self._mk_leased(cid_, ik)
        target = RUN * 10 + 9
        self.assertEqual(self._complete(jid, [target]), "candidate")
        rows = self._discovery_rows(cid_)
        self.assertEqual(rows[0]["status"], "candidate")
        self.assertEqual(rows[0]["result"]["candidate_cid"], target)
        self.assertEqual(self._pubchem_job_for(cid_, target), 1,
                         "candidate handoff 必须原子产生 pubchem_jobs 行")

    # ---- 10: handoff 异常全 rollback -------------------------------

    def test_10_handoff_failure_rollback(self):
        ik = _ik("ROLLBAAAAX")
        cid_ = self._mk_chemical({"inchikey": ik,
                                  "preferred_name": f"ut4-{RUN}-n10"})
        jid = self._mk_leased(cid_, ik)
        target = RUN * 10 + 10
        from api.services import enrichment as enr
        orig = enr.enqueue_job
        async def boom(*a, **k):
            raise RuntimeError("injected handoff failure")
        async def go():
            enr.enqueue_job = boom
            try:
                async with self.engine.begin() as db:
                    await orig(db, chemical_id=cid_, cid=1)  # ensure import path
                    from api.services.discovery import complete_discovery
                    await complete_discovery(db, job_id=jid, cid_list=[target])
            finally:
                enr.enqueue_job = orig
        with self.assertRaises(RuntimeError):
            _run(go())
        rows = self._discovery_rows(cid_)
        self.assertEqual(rows[0]["status"], "leased",
                         "handoff 失败 → identity 状态回滚(仍 leased 未定终态)")
        self.assertEqual(self._pubchem_job_for(cid_, target), 0,
                         "handoff 失败 → pubchem_jobs 零残留")

    # ---- 11: redirect → survivor ----------------------------------

    def test_11_redirect_to_survivor(self):
        ik = _ik("REDIRAAXAA")
        survivor = self._mk_chemical({"inchikey": ik,
                                      "preferred_name": f"ut4-{RUN}-n11s"})
        stale = self._mk_chemical({"preferred_name": f"ut4-{RUN}-n11t"})
        # 模拟 stale 行已被 absorb: 手工造 redirect
        from sqlalchemy import text
        async def rd():
            async with self.engine.begin() as db:
                await db.execute(text("""
                    INSERT INTO maintenance.chemical_identity_redirect
                        (old_chemical_id,canonical_chemical_id)
                    VALUES (:o,:n)
                """), {"o": stale, "n": survivor})
        _run(rd())
        jid = self._mk_leased(stale, ik)
        target = RUN * 10 + 11
        # stale 行已删(模拟 absorb 后), redirect 指向 survivor
        async def dele():
            async with self.engine.begin() as db:
                await db.execute(text("DELETE FROM chemistry.chemicals WHERE id=:i"),
                                 {"i": stale})
        _run(dele())
        self.assertEqual(self._complete(jid, [target]), "candidate")
        self.assertEqual(self._pubchem_job_for(survivor, target), 1,
                         "redirect 后 enrichment 必须落在 survivor")

    # ---- 12: chemicals 身份字段零直接写 ----------------------------

    def test_12_no_direct_identity_writes(self):
        ik = _ik("ZEROWRIAAX")
        cid_ = self._mk_chemical({"inchikey": ik,
                                  "preferred_name": f"ut4-{RUN}-n12"})
        jid = self._mk_leased(cid_, ik)
        target = RUN * 10 + 12
        self._complete(jid, [target])  # candidate 全流程
        from sqlalchemy import text
        async def go():
            async with self.engine.begin() as db:
                return (await db.execute(text(
                    "SELECT pubchem_cid,inchikey FROM chemistry.chemicals WHERE id=:i"),
                    {"i": cid_})).fetchone()
        row = _run(go())
        self.assertIsNone(row[0], "discovery 全流程绝不直写 pubchem_cid")
        self.assertEqual(row[1], ik, "inchikey 原样")


if __name__ == "__main__":
    unittest.main()
