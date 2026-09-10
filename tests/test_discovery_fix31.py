"""§3.1 修正集成测试。

1 savepoint 真隔离: 真实 PostgreSQL SQL error(非 RuntimeError)只回滚
  discovery savepoint, reaction/CB 主 transaction 仍可 commit, 无残留;
2 cid_list 无语义截断: 101+ CID 仍 AMBIGUOUS, 零 handoff, 不 first-hit;
3 lease 行锁契约: _verified_identity_lease SQL 含 FOR UPDATE。
"""

from __future__ import annotations

import asyncio
import os
import random
import string
import unittest

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
    return asyncio.run(coro)


def _ik(tag: str) -> str:
    return (f"{''.join(random.choices(string.ascii_uppercase, k=6))}{RUN % 1000000:08X}AB"
            f"CD{tag[:3].upper().ljust(3, 'X')}-{tag.ljust(10, 'X')[:10]}-A")[:27]


@unittest.skipUnless(DB_URL, "需要 PG 测试库")
class DiscoveryFix31Tests(unittest.TestCase):
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
                    "DELETE FROM maintenance.pubchem_identity_jobs "
                    "WHERE evidence_value LIKE :p"), {"p": f"%{RUN:08X}%"})
                await db.execute(text(
                    "DELETE FROM chemistry.chemicals "
                    "WHERE preferred_name LIKE :p"), {"p": f"ut31-{RUN}-%"})
        _run(clean())

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

    def _jobs(self, chemical_id: int) -> list:
        from sqlalchemy import text

        async def go():
            async with self.engine.begin() as db:
                rows = (await db.execute(text(
                    "SELECT id,status FROM maintenance.pubchem_identity_jobs "
                    "WHERE chemical_id=:c ORDER BY id"),
                    {"c": chemical_id})).fetchall()
                return list(rows)
        return _run(go())

    # ---- 1: reaction trigger savepoint 隔离真实 SQL error ----------

    def test_1_reaction_trigger_sqlerror_isolated(self):
        """真实 PG SQL error(约束冲突)在 enqueue 内爆发:
        主 reaction INSERT + statistics 仍 commit, discovery 无残留。"""
        from api.reactions import resolve_or_create_chemical
        from api.services import discovery as disc
        ik = _ik("SVPTREACT")
        orig = disc.enqueue_discovery
        # RUN 唯一 SMILES: 防残留行命中 EQUIVALENT 短路(短路则不触发
        # trigger 路径, is_new=False 假红)。氟代链(F 结尾)与历史醇链
        # (O 结尾)零冲突 — 醇链长度空间已被历史运行占满。
        uniq_smiles = "C" * (RUN % 20 + 3) + "F"

        async def poisoned(db, **kw):
            # 真实 PostgreSQL error: 向 NOT NULL 列插 NULL → server 拒绝,
            # 事务进 aborted — 只有 savepoint 能隔离。
            await db.execute(
                __import__("sqlalchemy").text(
                    "INSERT INTO maintenance.pubchem_identity_jobs "
                    "(chemical_id) VALUES (NULL)"))
            return orig(db, **kw)

        async def go():
            async with self.engine.begin() as db:
                disc.enqueue_discovery = poisoned
                try:
                    cid_ = await resolve_or_create_chemical(db, uniq_smiles)
                finally:
                    disc.enqueue_discovery = orig
                return cid_
        chemical_id, is_new = _run(go())  # 主事务 commit 成功=断言通过点
        self.assertTrue(is_new)
        self.assertEqual(self._jobs(chemical_id), [],
                         "SQL error 后 discovery 无残留")

    def test_2_cb_trigger_sqlerror_isolated(self):
        """CB fill: 同款真实 SQL error 隔离, 结构回补主事务仍 commit。"""
        from api.services import discovery as disc
        from api.services.cb import apply_structure_fill
        ik = _ik("SVPTCBXFIL")
        cid_ = self._mk_chem({"preferred_name": f"ut31-{RUN}-n2",
                              "smiles": "CCO"})
        orig = disc.enqueue_discovery

        async def poisoned(db, **kw):
            await db.execute(
                __import__("sqlalchemy").text(
                    "INSERT INTO maintenance.pubchem_identity_jobs "
                    "(chemical_id) VALUES (NULL)"))
            return orig(db, **kw)

        async def go():
            async with self.engine.begin() as db:
                disc.enqueue_discovery = poisoned
                try:
                    await apply_structure_fill(
                        db, cid_, {"smiles": "CCO", "inchikey": ik,
                                   "mol": None})
                finally:
                    disc.enqueue_discovery = orig
        _run(go())  # 主事务 commit 成功=断言通过点
        from sqlalchemy import text

        async def check():
            async with self.engine.begin() as db:
                ik_now = (await db.execute(text(
                    "SELECT inchikey FROM chemistry.chemicals WHERE id=:i"),
                    {"i": cid_})).scalar()
                return ik_now
        self.assertEqual(_run(check()), ik, "CB 结构回补主事务已 commit")
        self.assertEqual(self._jobs(cid_), [], "SQL error 后 discovery 无残留")

    # ---- 2: cid_list 无截断 ---------------------------------------

    def _mk_leased(self, chemical_id: int, ev: str) -> int:
        import hashlib
        from sqlalchemy import text
        from api.services.workqueue import lease_hash
        eh = hashlib.sha256(ev.encode()).hexdigest()

        async def go():
            async with self.engine.begin() as db:
                return int((await db.execute(text("""
                    INSERT INTO maintenance.pubchem_identity_jobs
                        (chemical_id,evidence_type,evidence_value,evidence_hash,
                         status,priority,dedupe_key,lease_owner,lease_token_hash,
                         lease_expires_at)
                    VALUES (:c,'inchikey',:ev,:eh,'leased',60,:dk,'ut31w',:th,
                            now()+interval '10 min')
                    RETURNING id
                """), {"c": chemical_id, "ev": ev, "eh": eh,
                       "dk": f"disc:{chemical_id}:inchikey:{eh}",
                       "th": lease_hash("t" * 43)})).scalar())
        return _run(go())

    def test_3_cids_over_100_still_ambiguous(self):
        """101+ CID: 不被 schema 截断, 正常 AMBIGUOUS, 零 handoff。"""
        from api.services.discovery import complete_discovery
        ik = _ik("OVER100AA")
        cid_ = self._mk_chem({"inchikey": ik,
                              "preferred_name": f"ut31-{RUN}-n3"})
        jid = self._mk_leased(cid_, ik)
        cids = [RUN * 1000 + i for i in range(101)]
        # schema 层先验: IdentityCompleteBody 接受 101 项
        from api.schemas.workapi import IdentityCompleteBody
        body = IdentityCompleteBody(
            job_id=jid, lease_token="t" * 43, cid_list=cids)
        self.assertEqual(len(body.cid_list), 101, "schema 不得截断/拒绝 101 项")

        async def go():
            async with self.engine.begin() as db:
                return await complete_discovery(db, job_id=jid, cid_list=cids)
        self.assertEqual(_run(go()), "ambiguous")
        self.assertEqual(self._jobs(cid_)[0][1], "ambiguous")
        from sqlalchemy import text

        async def pj():
            async with self.engine.begin() as db:
                return int((await db.execute(text(
                    "SELECT count(*) FROM maintenance.pubchem_jobs "
                    "WHERE chemical_id=:c"), {"c": cid_})).scalar())
        self.assertEqual(_run(pj()), 0, "101 CID 零 handoff, 绝不 first-hit")

    # ---- 3: lease 行锁契约 ----------------------------------------

    def test_4_verified_lease_sql_contract_for_update(self):
        """SQL contract: _verified_identity_lease 的语句必须含 FOR UPDATE
        且作用于 pubchem_identity_jobs(锁定行锁语义, 防漂移)。"""
        import inspect
        from api.workapi import _verified_identity_lease
        src = inspect.getsource(_verified_identity_lease)
        self.assertIn("FOR UPDATE", src,
                      "verified lease 必须 FOR UPDATE 行锁")
        self.assertIn("pubchem_identity_jobs", src)
        # 关键谓词防漂移: 只认 leased + token + 未过期
        self.assertIn("status='leased'", src)
        self.assertIn("lease_token_hash", src)
        self.assertIn("lease_expires_at>now()", src)

    def test_5_concurrent_second_terminal_rejected(self):
        """并发契约: 第一个终态提交后, 第二个 complete 同 lease →
        409(行锁+status 复核), 不落第二个终态。"""
        from fastapi import HTTPException
        from api.workapi import _verified_identity_lease
        from sqlalchemy import text
        ik = _ik("CONCURAAA")
        cid_ = self._mk_chem({"inchikey": ik,
                              "preferred_name": f"ut31-{RUN}-n5"})
        jid = self._mk_leased(cid_, ik)
        target = RUN * 10 + 5

        # worker_id/token 与 _mk_leased 持久化值对齐
        async def get_token_hash(db):
            return (await db.execute(text(
                "SELECT lease_token_hash FROM "
                "maintenance.pubchem_identity_jobs WHERE id=:j"),
                {"j": jid})).scalar()

        from api.services.workqueue import lease_hash
        token = "t" * 43

        async def scenario():
            # 事务 A: 行锁 + 落 candidate 终态
            async with self.engine.connect() as ca:
                async with ca.begin():
                    row = await _verified_identity_lease(ca, type(
                        "P", (), {"job_id": jid, "lease_token": token})(),
                        "ut31w")
                    assert row is not None
                    from api.services.discovery import complete_discovery
                    await complete_discovery(db=ca, job_id=jid,
                                             cid_list=[target])
            # 事务 B(在 A 提交后): 同 lease 再 complete → 409
            async with self.engine.connect() as cb_:
                async with cb_.begin():
                    try:
                        await _verified_identity_lease(cb_, type(
                            "P", (), {"job_id": jid, "lease_token": token})(),
                            "ut31w")
                    except HTTPException as exc:
                        return exc.status_code
                    return None
        self.assertEqual(_run(scenario()), 409,
                         "第二终态必须被行锁+status 复核拒绝")
        self.assertEqual(self._jobs(cid_)[0][1], "candidate")


if __name__ == "__main__":
    unittest.main()
