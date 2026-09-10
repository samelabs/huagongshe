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
    assert parse_qs(_u.query).get("test_sentinel") in (["hgs-test-db"], ["hgs-ephemeral-db"]), "sentinel 校验失败"
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

    def _mk_job(self, chemical_id: int, query_cid: int | None = None) -> int:
        """query_cid=None 保留旧夹具写法; 传值时模拟真实生产契约:
        pubchem_jobs.query_value = worker 发起的 CID 请求值。"""
        from sqlalchemy import text
        qv = str(query_cid) if query_cid is not None else "test"
        async def go():
            async with self.engine.begin() as db:
                return int((await db.execute(text("""
                    INSERT INTO maintenance.pubchem_jobs
                        (chemical_id, query_value, dedupe_key, priority, status, lease_owner, lease_token_hash, lease_expires_at)
                    VALUES (:c, :qv, :dk, 50, 'leased', :w, :h, now() + interval '10 min')
                    RETURNING id
                """), {"c": chemical_id, "qv": qv, "dk": f"ut3:{uuid.uuid4().hex}", "w": P + "w1",
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
        job = self._mk_job(row_id, query_cid=CID_B)
        resp = self._complete(job, self._payload(cid=CID_B, name=f"ut3-{RUN}-other"))
        row = self._get_row(row_id)
        self.assertIsNotNone(row, "CONFLICT 路径不得删除原行")
        self.assertEqual(row["pubchem_cid"], CID_A,
                         "CID 非空冲突不得覆盖, 主表现值必须保持 A")
        self.assertEqual(resp["status"], "ok")

    def test_2_existing_ik_a_incoming_ik_b_no_overwrite(self):
        """existing IK=A + incoming IK=B → 不覆盖。"""
        row_id = self._mk_chemical({"inchikey": IK_A})
        job = self._mk_job(row_id, query_cid=CID_A)
        self._complete(job, self._payload(ik=IK_B))
        row = self._get_row(row_id)
        self.assertIsNotNone(row)
        self.assertEqual(row["inchikey"], IK_A, "IK 非空不得被 incoming 覆盖")

    def test_3_null_cid_incoming_a_fills_empty(self):
        """existing CID NULL + incoming CID=A → 合法补空。"""
        row_id = self._mk_chemical({"preferred_name": f"ut3-{RUN}-n3"})
        job = self._mk_job(row_id, query_cid=CID_FILL)
        self._complete(job, self._payload(cid=CID_FILL))
        row = self._get_row(row_id)
        self.assertIsNotNone(row)
        self.assertEqual(row["pubchem_cid"], CID_FILL, "空 CID 必须能被补入")

    def test_4_incoming_cid_matches_other_row_reconciles(self):
        """incoming CID=A 且另一 HCID 已有 CID=A → 走 absorb 收敛到 survivor。"""
        other = self._mk_chemical({"pubchem_cid": CID_SHARED, "inchikey": IK_C,
                                   "preferred_name": f"ut3-{RUN}-n4a"})
        me = self._mk_chemical({"preferred_name": f"ut3-{RUN}-n4b"})
        job = self._mk_job(me, query_cid=CID_SHARED)
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
        job = self._mk_job(row_id, query_cid=CID_TX)
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
        job = self._mk_job(row_id, query_cid=CID_B)
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
        job = self._mk_job(row_id, query_cid=CID_FILL)
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
        job = self._mk_job(me, query_cid=CID_SHARED)
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

    # ---- §2.1 边界矩阵 ---------------------------------------------

    _CID_HOLDER = 910000001   # holder 行既有 CID

    def test_9_incoming_ik_conflicts_with_existing_cid_holder(self):
        """§2.1 一: source(NULL/NULL) + incoming(CID=holder.CID, IK≠holder.IK)
        → 必须 CONFLICT, 不得因 same CID 直接 absorb。"""
        ik_holder = "".join(random.choices(_string.ascii_uppercase, k=14)) + "-XXXXXXXXXX-A"
        ik_incoming = "".join(random.choices(_string.ascii_uppercase, k=14)) + "-YYYYYYYYYY-A"
        holder = self._mk_chemical({"pubchem_cid": self._CID_HOLDER, "inchikey": ik_holder,
                                    "preferred_name": f"ut3-{RUN}-n9h"})
        src = self._mk_chemical({"preferred_name": f"ut3-{RUN}-n9s"})
        job = self._mk_job(src, query_cid=self._CID_HOLDER)
        self._complete(job, self._payload(cid=self._CID_HOLDER, ik=ik_incoming))
        h, s = self._get_row(holder), self._get_row(src)
        # §2.2 修正: 逐 ID 真实查询 — 两个原始 ID 行都必须仍存在(非 dict 比较)
        self.assertIsNotNone(h, f"holder 行 id={holder} 必须仍存活")
        self.assertIsNotNone(s, f"source 行 id={src} 必须仍存活")
        self.assertNotEqual(holder, src, "两行必须是不同 HCID")
        # 无 redirect 指向 destructive merge
        from sqlalchemy import text
        async def cnt_redirect():
            async with self.engine.begin() as db:
                return int((await db.execute(text("""
                    SELECT count(*) FROM maintenance.chemical_identity_redirect
                    WHERE old_chemical_id IN (:a,:b)
                """), {"a": holder, "b": src})).scalar())
        self.assertEqual(_run(cnt_redirect()), 0, "holder IK 冲突不得产生 redirect")
        # 无 merge_log
        from sqlalchemy import text
        async def cnt():
            async with self.engine.begin() as db:
                return int((await db.execute(text("""
                    SELECT count(*) FROM maintenance.identity_merge_log
                    WHERE source_id IN (:a,:b) OR target_id IN (:a,:b)
                """), {"a": holder, "b": src})).scalar())
        self.assertEqual(_run(cnt()), 0, "holder IK 冲突不得 destructive merge")
        # holder IK 不变
        self.assertEqual(h["inchikey"], ik_holder)
        # source 不获得 CID / 不获得 incoming IK
        self.assertIsNone(s["pubchem_cid"])
        self.assertIsNone(s["inchikey"])

    def _details_count(self, chemical_id: int) -> int:
        from sqlalchemy import text
        async def go():
            async with self.engine.begin() as db:
                return int((await db.execute(text(
                    "SELECT count(*) FROM chemistry.chemical_pubchem WHERE chemical_id=:i"),
                    {"i": chemical_id})).scalar())
        return _run(go())

    def test_10_cid_conflict_withholds_payload_facts(self):
        """§2.1 二(1): CID 冲突时 payload 实体事实零写入。"""
        row_id = self._mk_chemical({"pubchem_cid": CID_A, "preferred_name": "OLD"})
        job = self._mk_job(row_id, query_cid=CID_B)
        self._complete(job, self._payload(cid=CID_B, name="WRONG"))
        row = self._get_row(row_id)
        self.assertIsNotNone(row)
        self.assertEqual(row["pubchem_cid"], CID_A, "CID 仍 A")
        self.assertEqual(row["preferred_name"], "OLD", "冲突时 preferred_name 不得被 incoming 覆盖")
        self.assertEqual(self._details_count(row_id), 0,
                         "conflict → chemical_pubchem 不得新增/更新")

    def test_11_ik_conflict_withholds_payload_facts(self):
        """§2.1 二(2): IK 冲突时普通事实也不得写。"""
        row_id = self._mk_chemical({"inchikey": IK_A, "preferred_name": "OLD"})
        job = self._mk_job(row_id, query_cid=CID_A)
        self._complete(job, self._payload(ik=IK_B, name="WRONG"))
        row = self._get_row(row_id)
        self.assertIsNotNone(row)
        self.assertEqual(row["inchikey"], IK_A, "IK 仍 A")
        self.assertEqual(row["preferred_name"], "OLD", "冲突时普通事实零写入")
        self.assertEqual(self._details_count(row_id), 0)

    def test_12_conflict_no_merge_log(self):
        """§2.1 二(3): conflict callback 不得产生 merge_log。"""
        row_id = self._mk_chemical({"pubchem_cid": CID_A, "preferred_name": "OLD"})
        job = self._mk_job(row_id, query_cid=CID_B)
        self._complete(job, self._payload(cid=CID_B, name="WRONG"))
        from sqlalchemy import text
        async def cnt():
            async with self.engine.begin() as db:
                return int((await db.execute(text(
                    "SELECT count(*) FROM maintenance.identity_merge_log WHERE source_id=:s"),
                    {"s": row_id})).scalar())
        self.assertEqual(_run(cnt()), 0)

    def test_13_query_value_cid_binding_contract(self):
        """§2.1 契约确认: 正常生产 job 的 query_value = worker 请求 CID;
        真实链路(完整回补)下 incoming CID 应等于 query_value CID。
        本用例以 query_cid=CID_A 造 job, incoming 同 CID → 正常补空写入,
        证明夹具可表达真实契约; binding 校验是否强制=待报告不扩大。"""
        row_id = self._mk_chemical({"preferred_name": f"ut3-{RUN}-n13"})
        job = self._mk_job(row_id, query_cid=CID_FILL)
        resp = self._complete(job, self._payload(cid=CID_FILL, name=f"ut3-{RUN}-n13t"))
        self.assertEqual(resp.get("chemical_id"), row_id)
        row = self._get_row(row_id)
        self.assertIsNotNone(row)
        self.assertEqual(row["pubchem_cid"], CID_FILL, "query_value=CID 且 incoming 同 CID → 合法补空")
        self.assertEqual(self._details_count(row_id), 1)

    # ---- §2.2 query binding 边界 -----------------------------------

    def _merge_log_count(self, *ids: int) -> int:
        from sqlalchemy import text
        async def go():
            async with self.engine.begin() as db:
                return int((await db.execute(text(
                    "SELECT count(*) FROM maintenance.identity_merge_log "
                    "WHERE source_id = ANY(:ids) OR target_id = ANY(:ids)"),
                    {"ids": list(ids)})).scalar())
        return _run(go())

    def test_14_query_a_incoming_a_normal_write(self):
        """A: query=A / incoming=A → 正常写入(§2.2 不阻断合法回补)。"""
        row_id = self._mk_chemical({"preferred_name": f"ut3-{RUN}-n14"})
        job = self._mk_job(row_id, query_cid=CID_FILL)
        self._complete(job, self._payload(cid=CID_FILL, name=f"ut3-{RUN}-n14t"))
        row = self._get_row(row_id)
        self.assertIsNotNone(row)
        self.assertEqual(row["pubchem_cid"], CID_FILL)
        self.assertEqual(self._details_count(row_id), 1)

    def test_15_query_a_incoming_b_zero_everything(self):
        """B: query=A / incoming=B → binding conflict: 主表零变化 /
        chemical_pubchem 零写入 / 零 merge_log。"""
        row_id = self._mk_chemical({"preferred_name": "OLD"})
        job = self._mk_job(row_id, query_cid=CID_A)
        resp = self._complete(job, self._payload(cid=CID_B, name="WRONG"))
        self.assertEqual(resp["status"], "ok", "binding conflict 仍正常完成出表")
        row = self._get_row(row_id)
        self.assertIsNone(row["pubchem_cid"], "主表 CID 零变化")
        self.assertEqual(row["preferred_name"], "OLD", "主表普通字段零变化")
        self.assertEqual(self._details_count(row_id), 0, "chemical_pubchem 零写入")
        self.assertEqual(self._merge_log_count(row_id), 0, "零 merge_log")

    def test_16_invalid_query_value_zero_entity_writes(self):
        """C: query_value 非法 / incoming=A → 零实体写入(job 仍完成出表)。"""
        row_id = self._mk_chemical({"preferred_name": "OLD"})
        job = self._mk_job(row_id, query_cid=None)  # 保留旧夹具 'test' = 非法值
        resp = self._complete(job, self._payload(cid=CID_A, name="WRONG"))
        self.assertEqual(resp["status"], "ok", "query 非法仍按现有口径完成出表")
        row = self._get_row(row_id)
        self.assertIsNone(row["pubchem_cid"], "非法 query → 零身份写入")
        self.assertEqual(row["preferred_name"], "OLD", "非法 query → 零普通写入")
        self.assertEqual(self._details_count(row_id), 0)

    def test_17_mismatch_ik_match_cannot_bypass_binding(self):
        """D: query=A / incoming=B + incoming IK 可匹配其他行 → 仍零 merge。"""
        # 另一行持 IK_X 且 CID=B — incoming IK 与它完全匹配
        other = self._mk_chemical({"pubchem_cid": CID_B, "inchikey": IK_B})
        row_id = self._mk_chemical({"preferred_name": "OLD"})
        job = self._mk_job(row_id, query_cid=CID_A)
        resp = self._complete(job, self._payload(cid=CID_B, ik=IK_B))
        self.assertEqual(resp["status"], "ok")
        row = self._get_row(row_id)
        other_row = self._get_row(other)
        self.assertIsNotNone(row, "query 行不得被 absorb 删除")
        self.assertIsNotNone(other_row, "IK 匹配行不得被 absorb 删除")
        self.assertIsNone(row["pubchem_cid"])
        self.assertEqual(row["preferred_name"], "OLD")
        self.assertEqual(self._details_count(row_id), 0)
        self.assertEqual(self._merge_log_count(row_id, other), 0,
                         "IK 可匹配其他行也不得绕过 query binding 产生 merge")

    def test_18_query_a_incoming_cid_missing_no_grant(self):
        """E: query=A / incoming CID 缺失 → 不产生 CID grant(IK-only 原规范)。"""
        row_id = self._mk_chemical({"preferred_name": f"ut3-{RUN}-n18"})
        job = self._mk_job(row_id, query_cid=CID_A)
        # incoming 无 CID, 仅 IK → 走 IK-only 原路径, 绝不从 query_value 发明 CID
        self._complete(job, self._payload(ik=IK_A, name=f"ut3-{RUN}-n18t"))
        row = self._get_row(row_id)
        self.assertIsNotNone(row)
        self.assertIsNone(row["pubchem_cid"], "incoming 无 CID → 不得借 query_value 获得 CID grant")
        self.assertEqual(row["inchikey"], IK_A, "IK-only 补空原规范保持")


if __name__ == "__main__":
    unittest.main()
