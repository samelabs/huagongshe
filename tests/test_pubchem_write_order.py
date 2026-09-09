"""§2 PubChem identity 写前裁定 — 真实生产顺序集成测试 (0909 规范收口)。

链路: worker callback(complete_job) → incoming CID/IK → identity validation
      → sync → reconcile。

测试库: 必须 TEST_DATABASE_URL 过 tests/db_gate.py 闸, 否则全 skip。
不打桩: complete_job 走真实 verified_lease(测试库内插真实 pubchem_jobs 租约行)。
每次运行使用唯一 CID/IK 基数, 避免跨运行残行触发 absorb。
"""

from __future__ import annotations

import hashlib
import os
import random
import re
import unittest
import uuid

DB_URL = None
try:
    from tests.db_gate import test_db_or_skip
    _raw = test_db_or_skip()
except Exception:
    _raw = None

if _raw:
    _stripped = _raw.split("?")[0]
    from urllib.parse import urlparse, parse_qs
    _u = urlparse(_raw)
    assert parse_qs(_u.query).get("test_sentinel") == ["hgs-test-db"], "sentinel 校验失败"
    print(f"[gate] integration db = {_u.path.lstrip('/')} sentinel = hgs-test-db")
    DB_URL = _stripped
    ASYNC_URL = re.sub(
        r"postgres(?:ql)?://([^:]+):([^@]+)@",
        lambda m: f"postgresql+asyncpg://{m.group(1)}:{m.group(2)}@", _stripped)

P = "UT3-PBORD-"
TOKEN = "ut3_" + "c" * 32
LEASE_TOKEN = "lt_" + "b" * 32
RUN = random.randint(10_000_000, 99_000_000)  # 本次运行唯一命名域
CID_A = RUN * 10 + 1   # test1 existing
CID_B = RUN * 10 + 2   # test1 incoming
# InChIKey 合法格式 = 纯大写字母(14-10-1); 用随机字母块防跨运行碰撞
import string as _string
_rblk = lambda: "".join(random.choices(_string.ascii_uppercase, k=14))
IK_A = f"{_rblk()}-AAAAAAAAAA-A"
IK_B = f"{_rblk()}-BBBBBBBBBB-B"
IK_C = f"{_rblk()}-CCCCCCCCCC-C"
CID_FILL = RUN * 10 + 3
CID_SHARED = RUN * 10 + 4  # test4
CID_TX = RUN * 10 + 5


def _lease_hash(value: str) -> bytes:
    return hashlib.sha256(value.encode()).digest()


def _run(coro):
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@unittest.skipUnless(DB_URL, "需要测试库 (TEST_DATABASE_URL 过闸)")
class PubChemWriteOrderTests(unittest.TestCase):
    """§2 五断言矩阵 — 真实 complete_job 链。"""

    @classmethod
    def setUpClass(cls):
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.pool import NullPool
        # NullPool: 每个测试独立事件循环, 连接不得跨 loop 复用
        cls.engine = create_async_engine(ASYNC_URL, echo=False, poolclass=NullPool)
        cls.lease_hash = staticmethod(_lease_hash)

        async def setup():
            from sqlalchemy import text
            async with cls.engine.begin() as db:
                await db.execute(text("""
                    INSERT INTO maintenance.worker_clients
                        (worker_id, token_hash, token_prefix, display_name, scopes, enabled, max_lease_jobs)
                    VALUES (:wid, :th, 'ut3', :wid, ARRAY['pubchem','cas']::text[], true, 10)
                    ON CONFLICT (worker_id) DO UPDATE
                      SET token_hash = EXCLUDED.token_hash, enabled = true,
                          disabled_at = NULL, scopes = ARRAY['pubchem','cas']::text[]
                """), {"wid": P + "w1",
                       "th": hashlib.sha256(TOKEN.encode()).digest()})
        _run(setup())

    @classmethod
    def tearDownClass(cls):
        _run(cls.engine.dispose())

    def setUp(self):
        # 清场: 只清本次运行命名域的行, 不碰其他测试数据
        from sqlalchemy import text
        async def clean():
            async with self.engine.begin() as db:
                await db.execute(text(
                    "DELETE FROM chemistry.chemicals WHERE preferred_name LIKE :p OR inchikey LIKE :ik"
                ), {"p": f"ut3-{RUN}-%", "ik": f"UT{RUN:08d}%"})
        _run(clean())

    # ---- helpers -------------------------------------------------

    def _mk_chemical(self, cols: dict) -> int:
        from sqlalchemy import text
        async def go():
            names = ", ".join(cols)
            params = ", ".join(f":{k}" for k in cols)
            async with self.engine.begin() as db:
                return int((await db.execute(text(
                    f"INSERT INTO chemistry.chemicals ({names}) VALUES ({params}) RETURNING id"
                ), cols)).scalar())
        return _run(go())

    def _mk_job(self, chemical_id: int) -> int:
        from sqlalchemy import text
        async def go():
            async with self.engine.begin() as db:
                return int((await db.execute(text("""
                    INSERT INTO maintenance.pubchem_jobs
                        (chemical_id, query_value, dedupe_key, priority, status, lease_owner, lease_token_hash, lease_expires_at)
                    VALUES (:c, 'test', :dk, 50, 'leased', :w, :h, now() + interval '10 min')
                    RETURNING id
                """), {"c": chemical_id, "dk": f"ut3:{uuid.uuid4().hex}", "w": P + "w1",
                       "h": self.lease_hash(LEASE_TOKEN)})).scalar())
        return _run(go())

    def _complete(self, job_id: int, payload: dict) -> dict:
        os.environ.setdefault("HGS_DATABASE_URL",
                              "postgresql+asyncpg://test:test@127.0.0.1:5432/test_hgs")
        from sqlalchemy.ext.asyncio import AsyncSession
        from api.workapi import complete_job, WorkerContext
        from api.schemas.workapi import CompleteBody

        async def go():
            async with AsyncSession(self.engine) as session:
                resp = await complete_job(
                    CompleteBody(job_id=job_id, lease_token=LEASE_TOKEN,
                                 result={"payload": payload}),
                    db=session,
                    worker=WorkerContext(worker_id=P + "w1", max_lease_jobs=10))
                return resp
        return _run(go())

    def _get_row(self, row_id: int):
        from sqlalchemy import text
        async def go():
            async with self.engine.begin() as db:
                row = (await db.execute(text("""
                    SELECT id, inchikey, pubchem_cid, preferred_name
                    FROM chemistry.chemicals WHERE id=:i
                """), {"i": row_id})).mappings().first()
                return dict(row) if row else None
        return _run(go())

    @staticmethod
    def _payload(cid=None, ik=None, name=None):
        core = {}
        if cid is not None:
            core["CID"] = cid
        if ik is not None:
            core["InChIKey"] = ik
        payload = {"core": core}
        if name:
            payload["record_title"] = name
        return payload

    # ---- §2 断言矩阵 ---------------------------------------------

    def test_1_existing_cid_a_incoming_b_no_overwrite(self):
        """existing CID=A + incoming CID=B → CONFLICT, 主表现值仍为 A。"""
        row_id = self._mk_chemical({"pubchem_cid": CID_A,
                                    "preferred_name": f"ut3-{RUN}-n1"})
        job = self._mk_job(row_id)
        resp = self._complete(job, self._payload(cid=CID_B, name=f"ut3-{RUN}-other"))
        row = self._get_row(row_id)
        self.assertIsNotNone(row, "CONFLICT 路径不得删除原行")
        self.assertEqual(row["pubchem_cid"], CID_A,
                         "CID 非空冲突不得覆盖, 主表现值必须保持 A")
        self.assertEqual(resp["status"], "ok")

    def test_2_existing_ik_a_incoming_ik_b_no_overwrite(self):
        """existing IK=A + incoming IK=B → 不覆盖。"""
        row_id = self._mk_chemical({"inchikey": IK_A})
        job = self._mk_job(row_id)
        self._complete(job, self._payload(ik=IK_B))
        row = self._get_row(row_id)
        self.assertIsNotNone(row)
        self.assertEqual(row["inchikey"], IK_A, "IK 非空不得被 incoming 覆盖")

    def test_3_null_cid_incoming_a_fills_empty(self):
        """existing CID NULL + incoming CID=A → 合法补空。"""
        row_id = self._mk_chemical({"preferred_name": f"ut3-{RUN}-n3"})
        job = self._mk_job(row_id)
        self._complete(job, self._payload(cid=CID_FILL))
        row = self._get_row(row_id)
        self.assertIsNotNone(row)
        self.assertEqual(row["pubchem_cid"], CID_FILL, "空 CID 必须能被补入")

    def test_4_incoming_cid_matches_other_row_reconciles(self):
        """incoming CID=A 且另一 HCID 已有 CID=A → 走 absorb 收敛到 survivor。"""
        other = self._mk_chemical({"pubchem_cid": CID_SHARED, "inchikey": IK_C,
                                   "preferred_name": f"ut3-{RUN}-n4a"})
        me = self._mk_chemical({"preferred_name": f"ut3-{RUN}-n4b"})
        job = self._mk_job(me)
        resp = self._complete(job, self._payload(cid=CID_SHARED))
        survivor = resp.get("chemical_id")
        self.assertIn(survivor, (me, other), "resp 必须返回 absorb 后真实 survivor")
        # 分叉收敛: 两行必须合一(被吸收行删除, 留 redirect)
        alive_me = self._get_row(me)
        alive_other = self._get_row(other)
        self.assertTrue(alive_me is None or alive_other is None,
                        "same-CID 分叉必须 absorb 收敛为一行")

    def test_5_transaction_failure_no_partial_identity(self):
        """事务中途失败不留下半写 identity。"""
        row_id = self._mk_chemical({"preferred_name": f"ut3-{RUN}-n5"})
        job = self._mk_job(row_id)
        os.environ.setdefault("HGS_DATABASE_URL",
                              "postgresql+asyncpg://test:test@127.0.0.1:5432/test_hgs")
        from api.services import workqueue as wq

        async def boom(db, cid_, new_cid):
            raise RuntimeError("injected mid-transaction failure")

        async def go():
            from sqlalchemy.ext.asyncio import AsyncSession
            from api.workapi import complete_job, WorkerContext
            from api.schemas.workapi import CompleteBody
            orig = wq.reconcile_pubchem_identity
            wq.reconcile_pubchem_identity = boom
            try:
                async with AsyncSession(self.engine) as session:
                    await complete_job(
                        CompleteBody(job_id=job, lease_token=LEASE_TOKEN,
                                     result={"payload": self._payload(cid=CID_TX)}),
                        db=session,
                        worker=WorkerContext(worker_id=P + "w1", max_lease_jobs=10))
            finally:
                wq.reconcile_pubchem_identity = orig
        with self.assertRaises(RuntimeError):
            _run(go())
        row = self._get_row(row_id)
        self.assertIsNotNone(row)
        self.assertIsNone(row["pubchem_cid"],
                          "事务中途失败: 已执行的 sync 写入必须整体回滚, 不留半写")

    def test_6_same_ik_does_not_bypass_cid_conflict(self):
        """incoming CID 冲突时, 不得因 incoming IK 恰巧相同而绕过。"""
        row_id = self._mk_chemical({"pubchem_cid": CID_A, "inchikey": IK_A,
                                    "preferred_name": f"ut3-{RUN}-n6"})
        job = self._mk_job(row_id)
        # incoming: CID=B(冲突) + IK=A(与行相同) → 必须仍按 CID 冲突 fail-closed
        self._complete(job, self._payload(cid=CID_B, ik=IK_A))
        row = self._get_row(row_id)
        self.assertIsNotNone(row)
        self.assertEqual(row["pubchem_cid"], CID_A,
                         "IK 相同不得绕过 CID 冲突")

    def test_7_valid_cid_incoming_ik_conflict_fails_closed(self):
        """incoming CID 合法但 incoming IK 与目标行 IK 冲突 → fail-closed(不写身份)。"""
        row_id = self._mk_chemical({"inchikey": IK_A,
                                    "preferred_name": f"ut3-{RUN}-n7"})
        job = self._mk_job(row_id)
        # 行 CID NULL, incoming CID=新值 + IK=B ≠ 行 IK=A → IK 冲突, 身份零写入
        self._complete(job, self._payload(cid=CID_FILL, ik=IK_B))
        row = self._get_row(row_id)
        self.assertIsNotNone(row)
        self.assertIsNone(row["pubchem_cid"],
                          "IK 冲突时 CID 也必须 fail-closed 不写")
        self.assertEqual(row["inchikey"], IK_A, "IK 冲突不得覆盖")

    def test_8_replay_no_second_destructive_merge(self):
        """callback 重放/幂等不产生第二次 destructive merge。"""
        other = self._mk_chemical({"pubchem_cid": CID_SHARED, "inchikey": IK_C,
                                   "preferred_name": f"ut3-{RUN}-n8a"})
        me = self._mk_chemical({"preferred_name": f"ut3-{RUN}-n8b"})
        job = self._mk_job(me)
        resp1 = self._complete(job, self._payload(cid=CID_SHARED))
        survivor1 = resp1.get("chemical_id")
        self.assertIn(survivor1, (me, other))
        # 重放同一结果: job 已出表, complete 必须 409(租约不存在) — 不再触碰数据
        with self.assertRaises(Exception):
            self._complete(job, self._payload(cid=CID_SHARED))
        from sqlalchemy import text
        async def count_merges():
            async with self.engine.begin() as db:
                return int((await db.execute(text("""
                    SELECT count(*) FROM maintenance.identity_merge_log
                    WHERE source_id IN (:a,:b) AND target_id IN (:a,:b)
                """), {"a": me, "b": other})).scalar())
        merges = _run(count_merges())
        self.assertEqual(merges, 1, "重放不得产生第二次 destructive merge")


if __name__ == "__main__":
    unittest.main()
