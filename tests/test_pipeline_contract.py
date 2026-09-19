"""数据管道端点契约锁定 (0911)。

锁的是管理后台 web/components/samelabs/PipelinePanel.tsx 实际消费的语义, 防回退:

1. 两链都返回 rows.today / rows.total, 且 total 是落库总量(非"今日"), 与 locales 求和一致
2. rate_1h 来自真实聚合 —— 与独立 SQL 一致, 且哨兵行(刚写入)必须被计入, 硬编码 0 会红
3. 不存在 not_found:-1 哨兵字段, 也不存在语义双关的 throughput 字段
4. latest 排序 NULLS LAST —— fetched_at 为空的旧行不得占据榜首
5. latest 行字段 / 前端 data.<chain>.<path> 消费路径, 与 API 返回逐一对齐
6. error 复活端点只认 cb/pb, 未知链 400

运行: . /tmp/hgs_test_env.sh && ./venv/bin/python -m unittest tests.test_pipeline_contract -v
依赖: 测试库(TEST_DATABASE_URL 过闸)。哨兵行挂在自增高位 id 上, tearDown 连同
子表行一起清光(CASCADE), 不触碰任何既有化合物数据。
"""
from __future__ import annotations

import asyncio
import json
import re
import unittest
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import api.admin as admin_mod
from api.admin import pipeline as pipeline_endpoint, revive_errors
from api.core.security import Actor

WEB_ROOT = Path(__file__).resolve().parent.parent / "web"
PANEL = WEB_ROOT / "components/samelabs/PipelinePanel.tsx"

# JS 成员/方法名: 解析 data.cb.x.y 时在遇到它们之前停止(它们不是 payload 字段)
_JS_MEMBERS = {"map", "filter", "length", "slice", "find", "some", "every", "join",
               "toFixed", "toString", "push", "reduce", "keys", "values", "entries"}


def _engine():
    from tests.db_gate import ProductionDbBlocked, require_test_db
    try:
        url = require_test_db()
    except ProductionDbBlocked:
        raise unittest.SkipTest("需要测试库 (TEST_DATABASE_URL 过闸)")
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url.split("://", 1)[1]
    url = url.split("?", 1)[0]
    # NullPool: 每个 asyncio.run 自建连接, 避免 asyncpg 连接跨事件循环复用
    # ("another operation is in progress")。
    return create_async_engine(url, poolclass=NullPool)


def _fake_admin() -> Actor:
    return Actor(id=1, username="pipeline-contract", display_name="pipeline-contract",
                 email="contract@test.local", role="admin", avatar_path=None,
                 auth_kind="session")


class PipelineContractTest(unittest.TestCase):
    """两级哨兵: 一条 PB 行带 fetched_at=now()(应上榜), 一条 PB 行 fetched_at=NULL(应沉底)。"""

    @classmethod
    def setUpClass(cls):
        cls.engine = _engine()
        cls.Session = async_sessionmaker(cls.engine, expire_on_commit=False)
        # 崩溃残留自愈: 按夹具特征清, 不依赖内存里的 id 列表
        asyncio.run(cls._purge_sentinels())

    @classmethod
    def tearDownClass(cls):
        asyncio.run(cls._purge_sentinels())
        asyncio.run(cls.engine.dispose())

    @classmethod
    async def _purge_sentinels(cls):
        """删除本夹具特征的行(含历史崩溃残留)。只在测试库执行, 不触碰任何真实化合物。"""
        async with cls.Session() as db:
            await db.execute(text(
                "DELETE FROM chemistry.chemicals "
                "WHERE id >= 100000000 AND preferred_name LIKE '契约哨兵%'"))
            await db.commit()

    # ── 夹具 ──────────────────────────────────────────────
    def setUp(self):
        admin_mod._PIPELINE_STATS_CACHE.clear()
        self.ids: list[int] = []
        asyncio.run(self._seed_all())
        admin_mod._PIPELINE_STATS_CACHE.clear()

    async def _seed_all(self):
        """两级哨兵: 新鲜行(fetched_at=now())与陈旧行(fetched_at=NULL)同一次事件循环内建好。"""
        self.fresh_id = await self._seed(fresh=True)
        self.stale_id = await self._seed(fresh=False)

    def tearDown(self):
        asyncio.run(self._cleanup())
        admin_mod._PIPELINE_STATS_CACHE.clear()

    async def _seed(self, *, fresh: bool) -> int:
        """建哨兵化学行 + CB 行 + PB 行; fresh=False 时 PB 行 fetched_at 留空。"""
        async with self.Session() as db:
            cid = int((await db.execute(text(
                "SELECT greatest(coalesce(max(id),0), 100000000) + 1 FROM chemistry.chemicals"
            ))).scalar())
            await db.execute(text("""
                INSERT INTO chemistry.chemicals
                  (id, smiles, molecular_formula, average_mass, monoisotopic_mass, inchikey,
                   mol, morgan_bfp, morgan_sfp, preferred_name, iupac_name, created_at, updated_at)
                VALUES (:id, 'CCO', 'C2H6O', 46.07, 46.0419, 'LFQSCWFLJHTTHZ-UHFFFAOYSA-N',
                        mol_from_smiles('CCO'), morganbv_fp(mol_from_smiles('CCO')),
                        morgan_fp(mol_from_smiles('CCO')), :nm, 'pipeline-contract', now(), now())
            """), {"id": cid, "nm": "契约哨兵新鲜" if fresh else "契约哨兵陈旧"})
            await db.execute(text("""
                INSERT INTO chemistry.chemical_cb
                  (chemical_id, cas_number, cb_number, locale, last_status, fetched_at, entry)
                VALUES (:id, '99999-99-9', :cb, 'zh-CN', 'ok',
                        now() - interval '5 minutes', '{}'::jsonb)
            """), {"id": cid, "cb": f"CONTRACT-{cid}"})
            await db.execute(text("""
                INSERT INTO chemistry.chemical_pubchem
                  (chemical_id, record_title, computed_properties, physical_properties,
                   ghs_classification, hazards, safety_measures, toxicity, regulatory, pharmacology,
                   uses_and_manufacturing, identifier_evidence, source_references, external_ids,
                   ghs_codes, reactivity, fetched_at, created_at, updated_at)
                VALUES (:id, :title, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb,
                        '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb,
                        '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb,
                        CASE WHEN :fresh THEN now() ELSE NULL END, now(), now())
            """), {"id": cid, "title": f"pipeline-contract-{cid}", "fresh": fresh})
            await db.commit()
            self.ids.append(cid)
            return cid

    async def _cleanup(self):
        # 按特征清(不依赖 ids), 崩溃后重跑也能自愈
        await type(self)._purge_sentinels()
        self.ids = []

    # ── 取数 ──────────────────────────────────────────────
    async def _payload(self) -> dict:
        admin_mod._PIPELINE_STATS_CACHE.clear()
        async with self.Session() as db:
            return await pipeline_endpoint(actor=_fake_admin(), db=db)

    async def _scalar(self, sql: str) -> int:
        async with self.Session() as db:
            return int((await db.execute(text(sql))).scalar())

    # ── 1. rows.today 两链同语义(E9-B: 有界口径, total 已删) ─────────────
    def test_rows_shape_both_chains(self):
        d = asyncio.run(self._payload())
        for chain in ("cb", "pb"):
            rows = d[chain]["rows"]
            self.assertEqual(set(rows), {"today"}, f"{chain}.rows 字段集变了")
            self.assertIsInstance(rows["today"], int)

        cb = d["cb"]
        self.assertEqual(cb["rows"]["today"],
                         sum(x["today"] for x in cb["locales"]), "cb.rows.today 与 locales 不符")
        # E9-B: rows.total / locale total / PB all-time 全部从 runtime 契约删除
        # (bounded 口径 — 无界大表 count 禁令, 见 test_pipeline_bounded_contract)

    # ── 2. rate_1h 是真实聚合 ────────────────────────────
    def test_rate_1h_is_real_aggregate(self):
        d = asyncio.run(self._payload())
        for chain, table in (("cb", "chemistry.chemical_cb"),
                             ("pb", "chemistry.chemical_pubchem")):
            expect = asyncio.run(self._scalar(
                f"SELECT count(*) FROM {table} WHERE fetched_at >= now() - interval '1 hour'"))
            self.assertEqual(d[chain]["rate_1h"], expect,
                             f"{chain}.rate_1h 与独立聚合不符(硬编码?)")
            self.assertGreaterEqual(d[chain]["rate_1h"], 1,
                                    f"{chain}.rate_1h 未计入刚写入的哨兵行")

    # ── 3. 假字段哨兵不得回潮 ────────────────────────────
    def test_no_sentinel_or_dual_semantics_fields(self):
        d = asyncio.run(self._payload())
        self.assertNotIn("not_found", json.dumps(d, ensure_ascii=False),
                         "not_found:-1 哨兵回潮")
        for chain in ("cb", "pb"):
            self.assertNotIn("throughput", d[chain], "throughput 双语义字段回潮")

    # ── 4. latest NULLS LAST + 字段形状 ──────────────────
    def test_latest_nulls_last_and_shape(self):
        d = asyncio.run(self._payload())
        for chain in ("cb", "pb"):
            rows = d["latest"][chain]
            self.assertIsInstance(rows, list)
            self.assertLessEqual(len(rows), 10)
            for r in rows:
                self.assertEqual(set(r), {"chain", "chemical_id", "source", "ref", "title", "at"},
                                 f"latest.{chain} 行字段集变了")

        ats = [r["at"] for r in d["latest"]["pb"]]
        non_null = [a for a in ats if a is not None]
        self.assertEqual(ats[:len(non_null)], non_null,
                         "latest.pb 出现'空时间行排在非空行之前' = NULLS LAST 失效")
        self.assertEqual(d["latest"]["pb"][0]["chemical_id"], self.fresh_id,
                         "最新行不是刚写入的哨兵 = 排序/新鲜度口径有误")
        stale_pos = [r["chemical_id"] for r in d["latest"]["pb"]].index(self.stale_id) \
            if self.stale_id in [r["chemical_id"] for r in d["latest"]["pb"]] else None
        if stale_pos is not None:
            self.assertGreaterEqual(stale_pos, len(non_null),
                                    "fetched_at=NULL 的哨兵行挤进了非空行区间")
        self.assertIsNotNone(d["pb"]["latest_at"], "pb.latest_at 不得为空")
        self.assertIsNotNone(d["cb"]["latest_at"], "cb.latest_at 不得为空")

    # ── 5. 前端消费路径与返回逐一对齐 ────────────────────
    def test_frontend_consumption_paths_exist(self):
        d = asyncio.run(self._payload())
        src = PANEL.read_text(encoding="utf-8")

        # (a) LatestRow 声明集 == 返回行字段集
        block = re.search(r"type LatestRow = \{([^}]*)\}", src)
        self.assertIsNotNone(block, "PipelinePanel 里找不到 LatestRow 声明")
        declared = {m.group(1) for m in re.finditer(r"([A-Za-z_][\w]*)\s*:", block.group(1))}
        self.assertEqual(declared, set(d["latest"]["cb"][0].keys()),
                         "LatestRow 声明与 API 返回字段不一致")

        # (b) 每个 data.<chain>.<path> 消费路径都要能在返回里解析出来
        paths = {m.group(0) for m in re.finditer(
            r"data\.(?:cb|pb|supplier|latest|gates|workers)\.[A-Za-z_][\w.]*", src)}
        self.assertTrue(paths, "未能从前端解析出任何 data.* 消费路径")
        for path in sorted(paths):
            self._assert_resolvable(d, path)

    def _assert_resolvable(self, payload: dict, path: str) -> None:
        cur = payload
        for tok in path.split(".")[1:]:           # 跳过 data
            if tok in _JS_MEMBERS or tok[0].isdigit():
                return
            self.assertIn(tok, cur, f"前端消费路径 {path} 在 API 返回中不存在")
            cur = cur[tok]

    # ── 6. 复活端点链名闸 ────────────────────────────────
    def test_revive_rejects_unknown_chain(self):
        async def call():
            async with self.Session() as db:
                return await revive_errors(chain="xx", actor=_fake_admin(), db=db)
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(call())
        self.assertEqual(ctx.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
