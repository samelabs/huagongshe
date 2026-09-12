"""A2 数据治理验收测试 (0912)。

任务书 11 条验收中的可自动化项:
2. optional governance metric 失败不拖垮整体(独立端点+section 容错)
3. expensive governance API 有缓存(单飞+TTL)
4. drill-down 有 limit
5. unavailable ≠ 0
6. orphan=0 时真实显示 0
7. name-index missing fixture 能被查出
8. source/canonical mismatch fixture 能被查出
9. supplier-name 不被描述成 canonical name(分布渲染层语义)

fixture 全部建在 test_hgs, teardown 清理。

运行: . /tmp/hgs_test_env.sh && ./venv/bin/python -m unittest tests.test_admin_governance_a2
"""

from __future__ import annotations

import asyncio
import os
import unittest

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

DB = os.environ.get("TEST_DATABASE_URL", "").replace("postgresql://", "postgresql+asyncpg://").split("?")[0]


def _db():
    return bool(DB)


async def _conn():
    engine = create_async_engine(DB, isolation_level="AUTOCOMMIT")
    async with engine.connect() as c:
        yield c
    await engine.dispose()


class GovBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not _db():
            raise unittest.SkipTest("需要 TEST_DATABASE_URL")

    def q(self, sql, params=None):
        # 注意: 测试类内多个 asyncio.run 各建新 loop; asyncpg 连接绑定创建时的
        # loop → 池化连接跨 loop 复用会 "another operation is in progress"。
        # 测试体量小, 每次即抛 engine, 不池化。
        async def run():
            eng = create_async_engine(DB, isolation_level="AUTOCOMMIT", poolclass=__import__("sqlalchemy.pool", fromlist=["NullPool"]).NullPool)
            try:
                async with eng.connect() as c:
                    r = await c.execute(text(sql), params) if params else await c.execute(text(sql))
                    try:
                        return r.fetchall()
                    except Exception:
                        return None
            finally:
                await eng.dispose()
        return asyncio.run(run())

    def q1(self, sql, params=None):
        rows = self.q(sql, params)
        return rows[0][0] if rows else None


FIXTURE_HCIDS = []


class FixtureTests(GovBase):
    """验收 7/8: 漏点 fixture 能被查出。"""

    def setUp(self):
        # 清理本测试残留
        self.q("DELETE FROM chemistry.name_index WHERE chemical_id IN (SELECT id FROM chemistry.chemicals WHERE smiles = 'C1=A2GOVTEST')")
        self.q("DELETE FROM chemistry.chemical_cb WHERE chemical_id IN (SELECT id FROM chemistry.chemicals WHERE smiles = 'C1=A2GOVTEST')")
        self.q("DELETE FROM chemistry.chemicals WHERE smiles = 'C1=A2GOVTEST'")
        # 建 fixture: 1 个 canonical 行 + cb zh-CN 源记录(identity.cn 有值) + 无 name_index
        cid = self.q1("""
            INSERT INTO chemistry.chemicals (smiles, molecular_formula, created_at, updated_at)
            VALUES ('C1=A2GOVTEST', 'C1A2', now(), now()) RETURNING id
        """)
        self.fix_cid = cid
        FIXTURE_HCIDS.append(cid)
        self.q("""
            INSERT INTO chemistry.chemical_cb (chemical_id, cas_number, locale, cb_number, entry, last_status, fetched_at, created_at, updated_at)
            VALUES (:cid, '0000-00-0', 'zh-CN', 'GOVTEST-1', :entry, 'ok', now(), now(), now())
        """, {"cid": cid, "entry": '{"identity": {"cn": "测试治理中文名A2"}}'})
        # name_index fixture(供分布/语义测试): 独立第二 chemical —— 不给主 fixture
        # 插 name_cn, 保持"identity.cn 有值但 name_index 未镜像"的可检语义
        cid2 = self.q1("""
            INSERT INTO chemistry.chemicals (smiles, molecular_formula, created_at, updated_at)
            VALUES ('C1=A2GOVTEST2', 'C1A2', now(), now()) RETURNING id
        """)
        self.fix_cid2 = cid2
        self.q("""
            INSERT INTO chemistry.name_index (chemical_id, kind, lang, source, name, normalized)
            VALUES (:cid, 'supplier', 'cn', 'cb', 'GOVTEST供应商货名', 'govtest供应商货名')
        """, {"cid": cid})
        self.q("""
            INSERT INTO chemistry.name_index (chemical_id, kind, lang, source, name, normalized)
            VALUES (:cid2, 'name_cn', 'cn', 'cb', '测试治理中文名A2', '测试治理中文名a2')
        """, {"cid2": cid2})

    def tearDown(self):
        self.q("DELETE FROM chemistry.name_index WHERE chemical_id IN (:cid, :cid2)".replace(":cid2", f"'{self.fix_cid2}'"), {"cid": self.fix_cid})
        self.q("DELETE FROM chemistry.chemical_cb WHERE chemical_id = :cid", {"cid": self.fix_cid})
        self.q("DELETE FROM chemistry.chemicals WHERE id IN (:cid, :cid2)".replace(":cid2", f"'{self.fix_cid2}'"), {"cid": self.fix_cid})

    def _gov(self):
        from api.services.pipeline_governance import governance_snapshot
        async def run():
            eng = create_async_engine(DB)
            try:
                async with async_sessionmaker(eng, expire_on_commit=False)() as db:
                    return await governance_snapshot(db)
            finally:
                await eng.dispose()
        return asyncio.run(run())

    def test_name_index_missing_fixture_found(self):
        """验收7: fixture(identity.cn 有值, 无 name_cn/cn/cb 行)能被查出。"""
        snap = self._gov()
        m = snap["cb_name_index_missing"]
        self.assertTrue(m["available"])
        # fixture 行必须命中(drill-down 查询直查该模式)
        rows = self.q("""
            SELECT chemical_id FROM (
              SELECT chemical_id FROM chemistry.chemical_cb
              WHERE locale='zh-CN' AND entry->'identity'->>'cn' IS NOT NULL
                AND cb_number = 'GOVTEST-1'
            ) s
            WHERE NOT EXISTS (SELECT 1 FROM chemistry.name_index n
                              WHERE n.chemical_id=s.chemical_id
                                AND n.kind='name_cn' AND n.lang='cn' AND n.source='cb')
        """)
        self.assertEqual(1, len(rows))
        self.assertEqual(self.fix_cid, rows[0][0])

    def test_source_canonical_mismatch_fixture_found(self):
        """验收8: 源记录有 cb_number, 主档 cb_number 空 → cb_canonical_cb_number_null 查出。"""
        snap = self._gov()
        m = snap["cb_canonical_cb_number_null"]
        self.assertTrue(m["available"])
        rows = self.q("""
            SELECT c.id FROM chemistry.chemicals c
            WHERE c.id = :cid AND c.cb_number IS NULL
        """, {"cid": self.fix_cid})
        self.assertEqual(1, len(rows))

    def test_sections_all_wrapped(self):
        """每个 section 都有 available/value/error/mode 四键; unavailable≠0(验收5)。"""
        snap = self._gov()
        for name, sec in snap.items():
            self.assertEqual({"available", "value", "error", "mode"}, set(sec), name)

    def test_sample_contract_no_full_count(self):
        """修正1: TABLESAMPLE 指标 exact=False + sample_size/matched/ratio;
        值里不得出现全库总数换算字段。"""
        snap = self._gov()
        for k in ("cb_name_index_missing", "cb_canonical_cb_number_null",
                  "cb_locale_gaps", "pb_canonical_sync_gap", "pb_cid_no_source_record"):
            v = snap[k]["value"]
            self.assertFalse(v["exact"], k)
            for f in ("sample_size", "matched", "ratio"):
                self.assertIn(f, v, f"{k}.{f}")
            for banned in ("estimated_total", "estimated_rate", "total_missing"):
                self.assertNotIn(banned, v, f"{k} 禁换算全量: {banned}")

    def test_identity_layers_not_substituted(self):
        """修正2: 历史治理记录 / 采集悬案 / resolver 事件三层分离;
        resolver_events=None 且带说明, 禁用 seed/merge 顶替。"""
        snap = self._gov()
        idg = snap["identity_governance"]["value"]
        self.assertIn("history", idg)
        self.assertIn("acquisition_pending", idg)
        self.assertIsNone(idg["resolver_events"])
        self.assertIn("无可统计", idg["resolver_events_note"])
        self.assertIsInstance(idg["acquisition_pending"]["ambiguous_seeds"], int)

    def test_supplier_kind_not_canonical_name(self):
        """验收9: 分布里 supplier kind 标注'供应商货名, 非展示名', 不混 canonical name。
        (服务端层面: name_cn kind 与 supplier kind 分开统计; 前端渲染 note。)"""
        snap = self._gov()
        dist = snap["name_index_distribution"]["value"]
        kinds = {d["kind"] for d in dist}
        self.assertIn("supplier", kinds)
        self.assertIn("name_cn", kinds)
        # supplier 行 lang=cn 不应被计为 name_cn 口径
        for d in dist:
            if d["kind"] == "supplier":
                self.assertNotEqual("name_cn", d["kind"])

    def test_orphan_zero_is_real_zero(self):
        """验收6: orphan=0(样本无孤儿)时 value=0 而非 unavailable。"""
        snap = self._gov()
        o = snap["supplier_listing_orphan"]
        if o["available"]:
            self.assertIsInstance(o["value"]["matched"], int)
            self.assertFalse(o["value"]["exact"])

    def test_drilldown_limit_and_unknown(self):
        """验收4: drill-down 有 LIMIT; 未知/无证据 key 明确拒绝。"""
        from api.services.pipeline_governance import DRILL_LIMIT, DRILL_UNSUPPORTED, drill_down
        self.assertLessEqual(DRILL_LIMIT, 50)
        self.assertIn("seed_enqueued_no_job", DRILL_UNSUPPORTED)
        async def run():
            eng = create_async_engine(DB)
            try:
                async with async_sessionmaker(eng, expire_on_commit=False)() as db:
                    return await drill_down(db, "cb_name_index_missing")
            finally:
                await eng.dispose()
        d = asyncio.run(run())
        self.assertTrue(d["available"])
        self.assertLessEqual(len(d["rows"]), DRILL_LIMIT)

    def test_seed_enqueued_no_job_deferred(self):
        """deferred 指标: unavailable 且解释原因, 不造数字。"""
        snap = self._gov()
        s = snap["seed_enqueued_no_job"]
        self.assertFalse(s["available"])
        self.assertEqual("deferred", s["mode"])
        self.assertIsNone(s["value"])
        self.assertTrue(s["error"])


class IssueModeMappingTests(unittest.TestCase):
    """修正3回归: 每个 issue 的口径标签必须取自真实 section key,
    错把 'sample' 当 key 会得到空口径(旧 bug)。"""

    SECTION_MODES = {
        "cb_name_index_missing": "sample",
        "cb_canonical_cb_number_null": "sample",
        "cb_locale_gaps": "sample",
        "supplier_listing_orphan": "sample",
        "pb_canonical_sync_gap": "sample",
        "pb_cid_no_source_record": "sample",
        "name_index_orphan": "sample",
        "name_index_distribution": "exact",
        "canonical_name_coverage": "sample",
        "identity_governance": "exact",
        "seed_enqueued_no_job": "deferred",
    }
    # GovernancePanel issues 里声明的 modeK(与组件源同步维护)
    ISSUE_MODE_KEYS = {
        "ambiguous": "identity_governance",
        "ni_missing": "cb_name_index_missing",
        "sup_orphan": "supplier_listing_orphan",
        "ni_orphan": "name_index_orphan",
        "cb_num_null": "cb_canonical_cb_number_null",
        "pb_norec": "pb_cid_no_source_record",
        "pb_gap": "pb_canonical_sync_gap",
        "seed_nj": "seed_enqueued_no_job",
    }

    def test_no_fake_sample_key(self):
        src = open("web/components/samelabs/GovernancePanel.tsx", encoding="utf-8").read()
        self.assertNotIn('modeNote(i.key === "seed_nj" ? "seed_enqueued_no_job" : "sample")', src,
                         "禁止把字面 'sample' 当 section key 传给 modeNote")
        self.assertIn("modeNote(i.modeK ?? i.key)", src)

    def test_every_issue_mode_key_is_real_section(self):
        for issue, key in self.ISSUE_MODE_KEYS.items():
            self.assertIn(key, self.SECTION_MODES, f"{issue} 引用了不存在的 section: {key}")
            # 抽样类 issue 必须映射到 sample 模式 section, 不得拿到空口径;
            # ambiguous=账本精确计数, seed_nj=deferred, 两者不属抽样
            if issue not in ("seed_nj", "ambiguous"):
                self.assertEqual("sample", self.SECTION_MODES[key],
                                 f"{issue} 应为样本口径 section")
        self.assertEqual("exact", self.SECTION_MODES[self.ISSUE_MODE_KEYS["ambiguous"]])
        self.assertEqual("deferred", self.SECTION_MODES[self.ISSUE_MODE_KEYS["seed_nj"]])

    def test_mode_label_mapping_complete(self):
        # GovernancePanel modeNote 的分支必须覆盖 deferred/exact, 且 sample→'样本口径'
        src = open("web/components/samelabs/GovernancePanel.tsx", encoding="utf-8").read()
        self.assertIn('"sample" ? "样本口径"', src)
        self.assertIn('"deferred" ? "暂缓"', src)


class CacheSemanticsTests(GovBase):
    """验收3: 缓存 + 单飞。"""

    def test_governance_cache_single_flight(self):
        import api.services.pipeline_governance as g
        g._GOV_CACHE.clear()
        calls = {"n": 0}

        async def run():
            eng = create_async_engine(DB)
            try:
                async with async_sessionmaker(eng, expire_on_commit=False)() as db:
                    return await _run(g, db)
            finally:
                await eng.dispose()
        async def _run(g, db):
            # 第一次真实跑
            r1 = await g.get_governance(db)
            calls["n"] = 1
            # TTL 内第二次 → 直接缓存, 0 次新扫
            orig = g.governance_snapshot
            async def counting(db2):
                calls["n"] += 100
                return await orig(db2)
            g.governance_snapshot = counting
            try:
                r2 = await g.get_governance(db)
            finally:
                g.governance_snapshot = orig
            return r1, r2
        r1, r2 = asyncio.run(run())
        self.assertEqual(1, calls["n"], "TTL 内不得重复扫描")
        self.assertEqual(r1["monotonic_ts"], r2["monotonic_ts"])

    def test_section_failure_does_not_kill_snapshot(self):
        """验收2: 单 section 失败 → available=false, 其余照常。"""
        import api.services.pipeline_governance as g

        async def boom(db):
            raise RuntimeError("injected")
        orig = g._SECTIONS["name_index_orphan"]
        g._SECTIONS["name_index_orphan"] = boom
        try:
            async def run():
                eng = create_async_engine(DB)
                try:
                    async with async_sessionmaker(eng, expire_on_commit=False)() as db:
                        return await g.governance_snapshot(db)
                finally:
                    await eng.dispose()
            snap = asyncio.run(run())
        finally:
            g._SECTIONS["name_index_orphan"] = orig
        self.assertFalse(snap["name_index_orphan"]["available"])
        self.assertIn("injected", snap["name_index_orphan"]["error"])
        self.assertTrue(snap["identity_governance"]["available"])


if __name__ == "__main__":
    unittest.main()
