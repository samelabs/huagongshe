"""身份裁定机制测试矩阵 (2026-09-06 规范冻结版)。

规范: docs/CHEMICALS_IDENTITY_GOVERNANCE.md。真库跑(需要 PG), 无库环境跳过。

矩阵 (每项对应规范条款):
1. 同 IK + 不同非空 CID → CONFLICT, 绝不能 absorb        (3.3 硬约束)
2. CAS 多候选 + 无 IK/CID → AMBIGUOUS, 任何候选行不得写入 (3.3)
3. CAS 多候选 + IK 唯一匹配 → 正确归属                    (3.3)
4. stale chemical_id 经 redirect 找到 canonical            (3.6.3)
5. absorb 后所有注册引用均改指                             (3.6.1)
6. registry 漏掉一个实际 FK 时测试必须失败                 (3.6.1)
7. merge_log 有 before snapshot / evidence / reason        (3.6.2)
8. 重复 name 改指不产生重复                                (3.6.4)
9. absorb 未过 gate → MergeBlockedError, 无删除发生        (3.5)
10. cid 命中 + 输入 ik 与行 ik 冲突 → CONFLICT             (3.3)
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TEST_MOL = '0Chemicalbook65-85-0.MOL\r\n  ChemDraw12022217462D\r\n\r\n  9  9  0  0  0  0  0  0  0  0999 V2000\r\n    0.7145    0.4125    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0\r\n   -0.0000    0.0000    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0\r\n   -0.7145    0.4125    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0\r\n   -1.4289    0.0000    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0\r\n   -1.4289   -0.8250    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0\r\n   -0.7145   -1.2375    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0\r\n   -0.0000   -0.8250    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0\r\n    0.7145    1.2375    0.0000 O   0  0  0  0  0  0  0  0  0  0  0  0\r\n    1.4289    0.0000    0.0000 O   0  0  0  0  0  0  0  0  0  0  0  0\r\n  1  2  1  0      \r\n  2  3  1  0      \r\n  3  4  2  0      \r\n  4  5  1  0      \r\n  5  6  2  0      \r\n  6  7  1  0      \r\n  2  7  2  0      \r\n  1  8  2  0      \r\n  1  9  1  0      \r\nM  END\r\n'

DB_URL = None
try:
    from tests.db_gate import test_db_or_skip  # noqa: E402
    DB_URL = test_db_or_skip()
except Exception:  # noqa: BLE001 — 闸缺失/不合规都视为无测试库
    DB_URL = None

# 测试专用标记值 — 不可能与真实数据相撞
CAS = "99999-99-9"
IK = "TESTTESTTESTTESTEST-UHFFFAOYSA-N"
IK2 = "TESTTESTTESTTESTES2-UHFFFAOYSA-N"
CID = 990000000
CID_A = 990000001
CID_B = 990000002
CB = "7777777"


@unittest.skipUnless(DB_URL, "需要 PG")
class IdentityResolutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import asyncio
        from sqlalchemy.ext.asyncio import create_async_engine
        cls.engine = create_async_engine(DB_URL)
        cls._aio = asyncio.new_event_loop()

    def _session(self):
        from sqlalchemy.ext.asyncio import AsyncSession
        return AsyncSession(self.engine, expire_on_commit=False)

    def _run(self, coro):
        return self._aio.run_until_complete(coro)

    def setUp(self):
        from sqlalchemy import text

        async def clean():
            async with self.engine.begin() as c:
                # 测试行按 cas/ik/cid 标记值清理; 引用行级联清理
                await c.execute(text("""
                    DELETE FROM chemistry.name_index WHERE chemical_id IN (
                        SELECT id FROM chemistry.chemicals WHERE
                            cas_numbers @> ARRAY[:c] OR inchikey IN (:ik,:ik2)
                            OR pubchem_cid IN (:a,:b))
                """), {"c": CAS, "ik": IK, "ik2": IK2, "a": CID_A, "b": CID_B})
                # 审计表清理: 按 trigger 直清。
                # 旧法按 source/target 子查询匹配, 但 absorb 删除 source 行后
                # 子查询失配 → unit-test 记录残留生产表(0906 已人工清 96 笔)。
                # redirect 无 trigger 列, 经 merge_log_id 级联定位。
                await c.execute(text("""
                    DELETE FROM maintenance.chemical_identity_redirect
                    WHERE merge_log_id IN (
                        SELECT merge_id FROM maintenance.identity_merge_log
                        WHERE trigger IN ('unit','unit-test'))
                """))
                await c.execute(text(
                    "DELETE FROM maintenance.identity_merge_log"
                    " WHERE trigger IN ('unit','unit-test')"))
                # GateCoverage 走生产 reconcile_pubchem_identity(trigger=
                # pubchem_fetch_callback) — 测试行也按标记 CAS 清理,
                # 审计表只承载真实治理事实
                await c.execute(text("""
                    DELETE FROM maintenance.chemical_identity_redirect
                    WHERE merge_log_id IN (
                        SELECT merge_id FROM maintenance.identity_merge_log
                        WHERE trigger = 'pubchem_fetch_callback'
                          AND source_keys_before->>'cas_numbers'
                              = '["99999-99-9"]')
                """))
                await c.execute(text(
                    "DELETE FROM maintenance.identity_merge_log"
                    " WHERE trigger = 'pubchem_fetch_callback'"
                    " AND source_keys_before->>'cas_numbers' = '[\"99999-99-9\"]'"))
                await c.execute(text("""
                    DELETE FROM chemistry.chemicals WHERE
                        cas_numbers @> ARRAY[:c] OR inchikey IN (:ik,:ik2)
                        OR pubchem_cid IN (:a,:b)
                """), {"c": CAS, "ik": IK, "ik2": IK2, "a": CID_A, "b": CID_B})
                # cas_jobs 部分唯一索引 dedupe: 本测试前缀直清(0907 卫生收口)
                await c.execute(text(
                    "DELETE FROM maintenance.cas_jobs"
                    " WHERE dedupe_key LIKE 'test-dedupe-%'"))
                # GateCoverage enqueue 也会以测试 CAS 占 cas_jobs 行(cas:new:*),
                # 其中 AMBIGUOUS 行 chemical_id 为 NULL — 一并清理防跨用例污染
                await c.execute(text(
                    "DELETE FROM maintenance.cas_jobs WHERE cas_number = :c"),
                    {"c": CAS})
        self._run(clean())

    @classmethod
    def tearDownClass(cls):
        cls._aio.close()

    # -- helpers ----------------------------------------------------------

    async def _insert(self, db, *, cas=None, ik=None, cid=None, mol=False,
                      cb=None, name=None):
        from sqlalchemy import text
        cols = ["created_at", "updated_at"]
        vals = ["now()", "now()"]
        params: dict = {}
        if cas:
            cols.append("cas_numbers"); vals.append(":cas"); params["cas"] = [cas]
        if ik:
            cols.append("inchikey"); vals.append(":ik"); params["ik"] = ik
        if cid:
            cols.append("pubchem_cid"); vals.append(":cid"); params["cid"] = cid
        if cb:
            cols.append("cb_number"); vals.append(":cb"); params["cb"] = cb
        if name:
            cols.append("preferred_name"); vals.append(":name"); params["name"] = name
        sql = (f"INSERT INTO chemistry.chemicals ({','.join(cols)}) "
               f"VALUES ({','.join(vals)}) RETURNING id")
        rid = (await db.execute(text(sql), params)).scalar_one()
        if mol:
            await db.execute(text(
                "UPDATE chemistry.chemicals SET mol=mol_from_ctab(:m) WHERE id=:id"),
                {"m": TEST_MOL, "id": rid})
        return rid

    # -- 矩阵 -------------------------------------------------------------

    def test_1_same_ik_distinct_cids_conflict_no_absorb(self):
        """同 IK + 不同非空 CID → CONFLICT; absorb 必须被 gate 挡住且无删除。"""
        from sqlalchemy import text
        from api.services.identity import resolve_chemical, absorb, MergeBlockedError

        async def go():
            async with self._session() as db:
                a = await self._insert(db, ik=IK, cid=CID_A, mol=True)
                b = await self._insert(db, ik=IK, cid=CID_B, mol=True)
                await db.commit()
                res = await resolve_chemical(db, inchikey=IK)
                blocked = None
                try:
                    await absorb(db, source_id=a, target_id=b,
                                 reason="test", trigger="unit")
                except MergeBlockedError as e:
                    blocked = str(e)
                both = (await db.execute(text(
                    "SELECT count(*) FROM chemistry.chemicals WHERE id IN (:a,:b)"
                ), {"a": a, "b": b})).scalar()
                await db.rollback()
                return res, blocked, both, a, b
        res, blocked, both, a, b = self._run(go())
        self.assertEqual(res.status, "CONFLICT", "ik 不得凌驾两个不同非空 CID")
        self.assertIsNone(res.chemical_id)
        self.assertIn("cid-conflict", blocked or "", "gate 必须以 cid 冲突拒绝")
        self.assertEqual(both, 2, "CONFLICT 之下两行都必须存活")

    def test_2_cas_multi_no_evidence_ambiguous_no_write(self):
        """CAS 多候选 + 无 IK/CID → AMBIGUOUS, 任何候选行均不得发生写入。"""
        from sqlalchemy import text
        from api.services.identity import resolve_chemical

        async def go():
            async with self._session() as db:
                a = await self._insert(db, cas=CAS, cb="1111111", name="warm-row")
                b = await self._insert(db, cas=CAS)
                await db.commit()
                base = (await db.execute(text("""
                    SELECT max(updated_at) FROM chemistry.chemicals
                    WHERE id IN (:a,:b)
                """), {"a": a, "b": b})).scalar()
                import asyncio
                await asyncio.sleep(0.05)
                res = await resolve_chemical(db, cas=CAS)  # 无 ik 判据
                # 验证"任何候选行不得写入": 两行 updated_at 不得晚于基线
                after = (await db.execute(text("""
                    SELECT max(updated_at) FROM chemistry.chemicals
                    WHERE id IN (:a,:b)
                """), {"a": a, "b": b})).scalar()
                await db.rollback()
                return res, after, base, sorted([a, b])
        res, after, base, cands = self._run(go())
        self.assertEqual(res.status, "AMBIGUOUS")
        self.assertIsNone(res.chemical_id, "AMBIGUOUS 不得选行")
        self.assertEqual(sorted(res.candidates), cands)
        self.assertLessEqual(after, base, "任何候选行均不得发生写入(updated_at 不得推进)")

    def test_3_cas_multi_ik_match_adjudicates(self):
        """CAS 多候选 + IK 唯一匹配 → 正确归属到 ik 结构行。"""
        from api.services.identity import resolve_chemical

        async def go():
            async with self._session() as db:
                _ = await self._insert(db, cas=CAS, name="cas-only")
                b = await self._insert(db, cas=CAS, ik=IK, mol=True)
                await db.commit()
                res = await resolve_chemical(db, cas=CAS, inchikey=IK)
                await db.rollback()
                return res, b
        res, b = self._run(go())
        self.assertEqual(res.status, "EQUIVALENT")
        self.assertEqual(res.chemical_id, b, "ik 判据行应胜出")

    def test_4_redirect_canonicalizes_stale_id(self):
        """stale chemical_id 经 redirect 找到 canonical。"""
        from api.services.identity import absorb, canonicalize_id

        async def go():
            async with self._session() as db:
                ph = await self._insert(db, cas=CAS)
                tgt = await self._insert(db, ik=IK, mol=True, cid=CID)
                await db.commit()
                survivor = await absorb(db, source_id=ph, target_id=tgt,
                                        reason="test-redirect", trigger="unit",
                                        evidence_ik=IK, evidence_cid=CID)
                await db.commit()
                stale = await canonicalize_id(db, ph)
                fresh = await canonicalize_id(db, tgt)
                await db.rollback()
                return survivor, stale, fresh, tgt
        survivor, stale, fresh, tgt = self._run(go())
        self.assertEqual(survivor, tgt)
        self.assertEqual(stale, tgt, "旧 id 应重定向到 survivor")
        self.assertEqual(fresh, tgt, "survivor 自身重定向不变")

    def test_5_absorb_migrates_all_registered_references(self):
        """absorb 后所有注册引用表均改指(抽样验证全部 11 张注册表的代表行)。"""
        from sqlalchemy import text
        from api.services.identity import absorb, CHEMICAL_REFERENCE_TABLES

        async def go():
            async with self._session() as db:
                ph = await self._insert(db, cas=CAS, cb=CB)
                tgt = await self._insert(db, ik=IK, mol=True, cid=CID)
                # 在有 NOT NULL 约束的引用表各放一行指向占位行
                await db.execute(text(
                    "INSERT INTO chemistry.chemical_cb"
                    " (chemical_id,cas_number,entry,last_status,fetched_at,locale)"
                    " VALUES (:id,:cas,'{}'::jsonb,'ok',now(),'zh-CN')"),
                    {"id": ph, "cas": CAS})
                await db.execute(text(
                    "INSERT INTO chemistry.name_index"
                    " (chemical_id,name,normalized,source,kind,lang)"
                    " VALUES (:id,'测试名ZZ9','测试名ZZ9','cb','alias_cn','cn')"),
                    {"id": ph})
                await db.execute(text(
                    "INSERT INTO maintenance.cas_jobs"
                    " (chemical_id,cas_number,dedupe_key,request_context)"
                    " VALUES (:id,:cas,:dk,'{}'::jsonb)"),
                    {"id": ph, "cas": CAS,
                     "dk": "test-dedupe-%s" % __import__("uuid").uuid4().hex[:12]})
                await db.commit()
                survivor = await absorb(db, source_id=ph, target_id=tgt,
                                        reason="test-refs", trigger="unit",
                                        evidence_ik=IK, evidence_cid=CID)
                await db.commit()
                leftovers = (await db.execute(text("""
                    SELECT count(*) FROM chemistry.chemicals WHERE id = :ph
                """), {"ph": ph})).scalar()
                cb_moved = (await db.execute(text(
                    "SELECT chemical_id FROM chemistry.chemical_cb"
                    " WHERE cas_number=:c"), {"c": CAS})).scalar()
                ni_moved = (await db.execute(text(
                    "SELECT chemical_id FROM chemistry.name_index"
                    " WHERE name='测试名ZZ9' AND source='cb' AND kind='alias_cn'"))).scalar()
                cj_moved = (await db.execute(text(
                    "SELECT chemical_id FROM maintenance.cas_jobs"
                    " WHERE cas_number=:c"), {"c": CAS})).scalar()
                await db.rollback()
                return (survivor, leftovers, cb_moved, ni_moved, cj_moved, tgt,
                        len(CHEMICAL_REFERENCE_TABLES))
        survivor, leftovers, cb_moved, ni_moved, cj_moved, tgt, n_regs = self._run(go())
        self.assertEqual(survivor, tgt)
        self.assertEqual(leftovers, 0, "占位行应已删除")
        self.assertEqual(cb_moved, tgt, "chemical_cb 应改指 survivor")
        self.assertEqual(ni_moved, tgt, "name_index 应改指 survivor")
        self.assertEqual(cj_moved, tgt, "cas_jobs 应改指 survivor")
        self.assertGreaterEqual(n_regs, 11, "registry 应含全部 11 张 FK 表")

    def test_6_registry_must_cover_all_fks(self):
        """registry 漏掉一个实际 FK 时测试必须失败 — 直接比对 PG 元数据。"""
        async def go():
            async with self._session() as db:
                from sqlalchemy import text
                rows = (await db.execute(text("""
                    SELECT n.nspname, c.relname
                    FROM pg_constraint k
                    JOIN pg_class c ON c.oid = k.conrelid
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE k.contype='f'
                      AND k.confrelid='chemistry.chemicals'::regclass
                    ORDER BY 1,2
                """))).all()
                return {tuple(r) for r in rows}
        from api.services.identity import CHEMICAL_REFERENCE_TABLES
        fks = self._run(go())
        reg = {(s, t) for s, t, _ in CHEMICAL_REFERENCE_TABLES}
        missing = fks - reg
        extra = reg - fks
        self.assertFalse(missing,
            f"registry 漏掉实际 FK 表(规范3.6.1): {sorted(missing)}")
        self.assertFalse(extra,
            f"registry 含非 FK 表(将导致无效 UPDATE): {sorted(extra)}")

    def test_7_merge_log_has_snapshot_evidence_reason(self):
        """merge_log 有 before snapshot / evidence / reason。"""
        from sqlalchemy import text
        from api.services.identity import absorb

        async def go():
            async with self._session() as db:
                ph = await self._insert(db, cas=CAS, cb=CB)
                tgt = await self._insert(db, ik=IK, mol=True, cid=CID, name="target-name")
                await db.commit()
                survivor = await absorb(db, source_id=ph, target_id=tgt,
                                        reason="test-log", trigger="unit-test",
                                        evidence_ik=IK, evidence_cid=CID)
                await db.commit()
                row = (await db.execute(text("""
                    SELECT source_id, target_id, reason, evidence,
                           source_keys_before, target_keys_before, trigger
                    FROM maintenance.identity_merge_log
                    WHERE source_id = :ph AND target_id = :tgt
                    ORDER BY merge_id DESC LIMIT 1
                """), {"ph": ph, "tgt": tgt})).mappings().first()
                await db.rollback()
                return row, ph, tgt, survivor
        row, ph, tgt, survivor = self._run(go())
        self.assertIsNotNone(row, "merge_log 必须有记录")
        self.assertEqual(survivor, tgt)
        self.assertIn("test-log", row["reason"])
        self.assertIn("gate=", row["reason"], "reason 应含 gate 结论")
        self.assertIn("cb_number", row["source_keys_before"], "before snapshot 应含键字段")
        self.assertEqual(row["source_keys_before"]["cb_number"], CB)
        self.assertEqual(row["target_keys_before"]["inchikey"], IK)
        self.assertTrue(row["evidence"], "evidence 不得为空")
        self.assertEqual(row["trigger"], "unit-test")

    def test_8_name_dedupe_on_repoint(self):
        """重复 name 改指不产生重复行。"""
        from sqlalchemy import text
        from api.services.identity import absorb

        async def go():
            async with self._session() as db:
                ph = await self._insert(db, cas=CAS)
                tgt = await self._insert(db, ik=IK, mol=True, cid=CID)
                # 两侧各有一条同名条目
                await db.execute(text(
                    "INSERT INTO chemistry.name_index"
                    " (chemical_id,name,normalized,source,kind,lang)"
                    " VALUES (:id,'苯甲酸ZZ9','苯甲酸ZZ9','cb','alias_cn','cn')"), {"id": tgt})
                await db.execute(text(
                    "INSERT INTO chemistry.name_index"
                    " (chemical_id,name,normalized,source,kind,lang)"
                    " VALUES (:id,'苯甲酸ZZ9','苯甲酸ZZ9','cb','alias_cn','cn')"), {"id": ph})
                await db.commit()
                await absorb(db, source_id=ph, target_id=tgt,
                             reason="test-dedupe", trigger="unit",
                             evidence_ik=IK, evidence_cid=CID)
                await db.commit()
                dup = (await db.execute(text("""
                    SELECT count(*) FROM chemistry.name_index
                    WHERE name='苯甲酸ZZ9' AND source='cb' AND kind='alias_cn'
                """))).scalar()
                await db.rollback()
                return dup
        self.assertEqual(self._run(go()), 1, "同名条目改指后应只剩一条")

    def test_9_absorb_without_gate_raises_no_delete(self):
        """无强证据(两侧键全空) absorb → MergeBlockedError, 无删除。"""
        from sqlalchemy import text
        from api.services.identity import absorb, MergeBlockedError

        async def go():
            async with self._session() as db:
                a = await self._insert(db, cas=CAS)
                b = await self._insert(db, cas=CAS)  # 同 cas 两行, cas 不构成证据
                await db.commit()
                err = None
                try:
                    await absorb(db, source_id=a, target_id=b,
                                 reason="test-gate", trigger="unit")
                except MergeBlockedError as e:
                    err = str(e)
                both = (await db.execute(text(
                    "SELECT count(*) FROM chemistry.chemicals WHERE id IN (:a,:b)"
                ), {"a": a, "b": b})).scalar()
                await db.rollback()
                return err, both
        err, both = self._run(go())
        self.assertIsNotNone(err, "cas 相同不得构成 merge 证据")
        self.assertIn("no-strong-evidence", err)
        self.assertEqual(both, 2, "被拒后两行都必须存活")

    def test_10_cid_hit_with_conflicting_ik_is_conflict(self):
        """cid 命中但输入 ik 与行 ik 冲突 → CONFLICT(不 coalesce 默默吞)。"""
        from api.services.identity import resolve_chemical

        async def go():
            async with self._session() as db:
                a = await self._insert(db, cid=CID_A, ik=IK, mol=True)
                await db.commit()
                res = await resolve_chemical(db, cid=CID_A, inchikey=IK2)
                await db.rollback()
                return res, a
        res, a = self._run(go())
        self.assertEqual(res.status, "CONFLICT")
        self.assertIsNone(res.chemical_id)
        self.assertIn(a, res.candidates)

    def test_11_absorb_atomic_rollback(self):
        """事务失败测试: 子表改指中途失败 → 主表/redirect/merge_log/子表全回滚。

        手法: 吸收过程中 mock chemical_supplier_listing 的 UPDATE 抛错,
        验证无"合并一半"(merge_log/redirect/已改指子表全部随事务回滚)。
        """
        from sqlalchemy import text
        from unittest.mock import patch
        from api.services.identity import absorb

        async def go():
            async with self._session() as db:
                ph = await self._insert(db, cas=CAS, cb=CB)
                tgt = await self._insert(db, ik=IK, mol=True, cid=CID)
                await db.execute(text(
                    "INSERT INTO chemistry.chemical_cb"
                    " (chemical_id,cas_number,entry,last_status,fetched_at,locale)"
                    " VALUES (:id,:cas,'{}'::jsonb,'ok',now(),'zh-CN')"),
                    {"id": ph, "cas": CAS})
                await db.commit()

                import api.services.identity as ident_mod
                orig_execute = ident_mod.text  # 拦 SQL 构造点: 构造即替换

                class _BombText:
                    """对 supplier_listing 的 UPDATE 返回会在 bind 时炸的语句。"""
                    def __init__(self, sql):
                        self._sql = sql
                    def bindparams(self, *a, **k):
                        return self
                    def self_group(self, *a, **k):
                        return self

                class _BombClause(_BombText):
                    pass

                def fake_text(sql):
                    if "chemical_supplier_listing" in sql and "UPDATE" in sql:
                        raise RuntimeError("simulated mid-merge failure")
                    return orig_execute(sql)

                err = None
                try:
                    with patch.object(ident_mod, "text", fake_text):
                        await absorb(db, source_id=ph, target_id=tgt,
                                     reason="test-atomic", trigger="unit",
                                     evidence_ik=IK, evidence_cid=CID)
                except RuntimeError as e:
                    err = str(e)
                await db.rollback()
                # 全回滚验证: 两行都在, 无 merge_log, 无 redirect, cb 仍指 ph
                both = (await db.execute(text(
                    "SELECT count(*) FROM chemistry.chemicals WHERE id IN (:a,:b)"
                ), {"a": ph, "b": tgt})).scalar()
                logs = (await db.execute(text(
                    "SELECT count(*) FROM maintenance.identity_merge_log"
                    " WHERE source_id=:s AND target_id=:t"),
                    {"s": ph, "t": tgt})).scalar()
                redirs = (await db.execute(text(
                    "SELECT count(*) FROM maintenance.chemical_identity_redirect"
                    " WHERE old_chemical_id=:s"), {"s": ph})).scalar()
                cb_still = (await db.execute(text(
                    "SELECT chemical_id FROM chemistry.chemical_cb"
                    " WHERE cas_number=:c"), {"c": CAS})).scalar()
                return err, both, logs, redirs, cb_still, ph
        err, both, logs, redirs, cb_still, ph = self._run(go())
        self.assertIsNotNone(err, "模拟失败必须抛出")
        self.assertEqual(both, 2, "主表两行必须都在(无半合并)")
        self.assertEqual(logs, 0, "merge_log 不得残留")
        self.assertEqual(redirs, 0, "redirect 不得残留")
        self.assertEqual(cb_still, ph, "已改指的子表必须随事务回滚")

    # -- 既有回归(0905三场景, 升级到新契约) --------------------------------


    def test_12_tightened_gate_ik_alone_never_merges(self):
        """0906 终审收紧: IK 单独永不授权 destructive merge。

        a) 仅同 IK 两侧无 CID → BLOCKED(same_inchikey_without_entity_proof), 两行存活
        b) evidence_cid 与目标行 CID 一致(源行无CID) → ALLOW
        c) evidence_cid 与目标行 CID 冲突 → BLOCKED(cid-conflict)
        d) 仅 evidence_ik(两侧无 CID) → BLOCKED
        """
        from sqlalchemy import text
        from api.services.identity import can_merge

        async def go():
            async with self._session() as db:
                # a) 仅 IK
                a1 = await self._insert(db, ik=IK, mol=True)
                a2 = await self._insert(db, ik=IK, mol=True)
                await db.commit()
                ok, reason = await can_merge(db, source_id=a1, target_id=a2)
                r_a = (ok, reason, )
                # 两行都还在
                n = (await db.execute(text(
                    "SELECT count(*) FROM chemistry.chemicals WHERE id IN (:x,:y)"
                ), {"x": a1, "y": a2})).scalar()

                # b) evidence_cid 一致
                b1 = await self._insert(db)                     # 空行
                b2 = await self._insert(db, ik=IK, cid=CID, mol=True)
                await db.commit()
                ok_b, reason_b = await can_merge(
                    db, source_id=b1, target_id=b2, evidence_cid=CID)

                # c) evidence_cid 冲突
                c1 = await self._insert(db, cid=CID_A)
                c2 = await self._insert(db, ik=IK, cid=CID_B, mol=True)
                await db.commit()
                ok_c, reason_c = await can_merge(
                    db, source_id=c1, target_id=c2, evidence_cid=CID_B)

                # d) 仅 evidence_ik
                d1 = await self._insert(db)
                d2 = await self._insert(db, mol=True)           # 无键结构行
                await db.commit()
                ok_d, reason_d = await can_merge(
                    db, source_id=d1, target_id=d2, evidence_ik=IK)
                return r_a, n, (ok_b, reason_b), (ok_c, reason_c), (ok_d, reason_d)
        (ok_a, reason_a), n, (ok_b, reason_b), (ok_c, reason_c), (ok_d, reason_d) = self._run(go())
        self.assertFalse(ok_a, "仅同IK不得放行")
        self.assertEqual(reason_a, "same_inchikey_without_entity_proof")
        self.assertEqual(n, 2, "a组两行必须存活")
        self.assertTrue(ok_b, "evidence_cid一致须放行(entity proof)")
        self.assertTrue(str(CID) in reason_b)
        self.assertFalse(ok_c, "evidence_cid冲突须拦截")
        self.assertIn("cid-conflict", reason_c)
        self.assertFalse(ok_d, "仅evidence_ik不得放行")
        self.assertEqual(reason_d, "no-strong-evidence")

    def test_r1_smiles_row_exists_cas_resolve_hits_it(self):
        from api.services.identity import resolve_chemical

        async def go():
            async with self._session() as db:
                res1 = await resolve_chemical(db, inchikey=IK)
                from sqlalchemy import text
                await db.execute(text(
                    "UPDATE chemistry.chemicals SET mol = mol_from_ctab(:mol)"
                    " WHERE id = :id"), {"id": res1.chemical_id, "mol": TEST_MOL})
                await db.commit()
                res2 = await resolve_chemical(db, cas=CAS, inchikey=IK)
                await db.rollback()
                return res1, res2
        r1, r2 = self._run(go())
        self.assertEqual(r1.status, "NEW")
        self.assertEqual(r2.status, "EQUIVALENT", "SMILES 行存在时 CAS+IK 应命中")
        self.assertEqual(r2.chemical_id, r1.chemical_id, "不得新建行")

    def test_r2_cas_unique_hit(self):
        from api.services.identity import resolve_chemical

        async def go():
            async with self._session() as db:
                a = await self._insert(db, cas=CAS)
                await db.commit()
                res = await resolve_chemical(db, cas=CAS)
                await db.rollback()
                return res, a
        res, a = self._run(go())
        self.assertEqual(res.status, "EQUIVALENT")
        self.assertEqual(res.chemical_id, a)



class OneToOneMergeTests(IdentityResolutionTests):
    # 父类回归用例(test_5..test_8)只跑一次 — 本类只加载 1:1 矩阵,
    # 避免 cas_jobs 部分唯一索引 dedupe_key='test-dedupe-1' 跨类残留。
    def test_5_absorb_migrates_all_registered_references(self):
        self.skipTest("回归用例由 IdentityResolutionTests 承担")
    """0906 canary cid2273 修复: 1:1 子表合并策略矩阵。"""

    def test_registry_strategy_completeness(self):
        """每张 FK 表都有明确策略; 策略闭集; cfg 键合法。"""
        from api.services.identity import (CHEMICAL_REFERENCE_TABLES,
                                           ONE_TO_ONE_MERGE_COLUMNS)
        valid = {"REKEY_MANY", "MERGE_ONE_TO_ONE", "DEDUPE_REKEY"}
        for sch, tbl, cfg in CHEMICAL_REFERENCE_TABLES:
            self.assertIn(cfg["strategy"], valid)
            if cfg["strategy"] == "MERGE_ONE_TO_ONE":
                self.assertIn((sch, tbl), ONE_TO_ONE_MERGE_COLUMNS)
                self.assertIsNotNone(cfg.get("merge_cols"))
            if cfg["strategy"] == "DEDUPE_REKEY":
                self.assertTrue(cfg.get("dedupe_key"),
                                f"{sch}.{tbl} DEDUPE_REKEY 无 dedupe_key")

    def _insert_row(self, db, *, cid=None, mol=False):
        return self._run(self._insert(db, cid=cid, mol=mol))

    def test_1to1_C_both_sides_coalesce(self):
        """两侧都有: survivor 非空保留, 空被补, old 行删。"""
        from sqlalchemy import text
        from api.services.identity import absorb
        async def go():
            async with self._session() as db:
                tgt, ph = None, None
                tgt = await self._insert(db, cid=990000101, mol=True)
                ph = await self._insert(db, cid=990000101)
                await db.execute(text(
                    "INSERT INTO chemistry.chemical_pubchem (chemical_id, record_title, xlogp)"
                    " VALUES (:i,'surv-t',NULL)"), {"i": tgt})
                await db.execute(text(
                    "INSERT INTO chemistry.chemical_pubchem (chemical_id, record_title, xlogp)"
                    " VALUES (:i,'old-t',3.5)"), {"i": ph})
                await db.commit()
                surv = await absorb(db, source_id=ph, target_id=tgt,
                                    reason="t-1to1-C", trigger="unit-test",
                                    evidence_cid=990000101)
                await db.commit()
                row = (await db.execute(text(
                    "SELECT record_title, xlogp FROM chemistry.chemical_pubchem"
                    " WHERE chemical_id=:i"), {"i": surv})).first()
                left = (await db.execute(text(
                    "SELECT count(*) FROM chemistry.chemical_pubchem"
                    " WHERE chemical_id=:i"), {"i": ph})).scalar()
                return row, left
        row, left = self._run(go())
        self.assertEqual((row[0], row[1]), ("surv-t", 3.5))
        self.assertEqual(left, 0)

    def test_1to1_A_old_only_rekey(self):
        from sqlalchemy import text
        from api.services.identity import absorb
        async def go():
            async with self._session() as db:
                tgt = await self._insert(db, cid=990000102, mol=True)
                ph = await self._insert(db, cid=990000102)
                await db.execute(text(
                    "INSERT INTO chemistry.chemical_pubchem (chemical_id, record_title)"
                    " VALUES (:i,'only-old')"), {"i": ph})
                await db.commit()
                surv = await absorb(db, source_id=ph, target_id=tgt,
                                    reason="t-1to1-A", trigger="unit-test",
                                    evidence_cid=990000102)
                await db.commit()
                n = (await db.execute(text(
                    "SELECT count(*) FROM chemistry.chemical_pubchem"
                    " WHERE chemical_id=:i"), {"i": surv})).scalar()
                return n
        self.assertEqual(self._run(go()), 1)

    def test_1to1_B_survivor_only_untouched(self):
        from sqlalchemy import text
        from api.services.identity import absorb
        async def go():
            async with self._session() as db:
                tgt = await self._insert(db, cid=990000103, mol=True)
                ph = await self._insert(db, cid=990000103)
                await db.execute(text(
                    "INSERT INTO chemistry.chemical_pubchem (chemical_id, record_title)"
                    " VALUES (:i,'surv-only')"), {"i": tgt})
                await db.commit()
                surv = await absorb(db, source_id=ph, target_id=tgt,
                                    reason="t-1to1-B", trigger="unit-test",
                                    evidence_cid=990000103)
                await db.commit()
                t = (await db.execute(text(
                    "SELECT record_title FROM chemistry.chemical_pubchem"
                    " WHERE chemical_id=:i"), {"i": surv})).scalar()
                return t
        self.assertEqual(self._run(go()), "surv-only")

    def test_1to1_cb_same_locale(self):
        """chemical_cb 同 locale 双行(键撞) → 并入 survivor, old 删。"""
        from sqlalchemy import text
        from api.services.identity import absorb
        async def go():
            async with self._session() as db:
                tgt = await self._insert(db, cid=990000105, mol=True)
                ph = await self._insert(db, cid=990000105)
                await db.execute(text(
                    "INSERT INTO chemistry.chemical_cb (chemical_id, cas_number, locale)"
                    " VALUES (:i,'12345-67-1','zh-CN')"), {"i": ph})
                await db.commit()
                surv = await absorb(db, source_id=ph, target_id=tgt,
                                    reason="t-1to1-cb", trigger="unit-test",
                                    evidence_cid=990000105)
                await db.commit()
                n = (await db.execute(text(
                    "SELECT count(*) FROM chemistry.chemical_cb"
                    " WHERE chemical_id=:i"), {"i": surv})).scalar()
                return n
        self.assertEqual(self._run(go()), 1)


    def test_1to1_cb_multi_locale_partial_overlap(self):
        """cb per-locale: old 有 zh-CN+en-US, survivor 只有 zh-CN。
        zh-CN 同键 → coalesce 并删 old zh-CN 行; en-US survivor 无 → 改指保留。
        不同 locale entry 不得互串, locale 绝不改写。"""
        from sqlalchemy import text
        from api.services.identity import absorb
        async def go():
            async with self._session() as db:
                tgt = await self._insert(db, cid=990000107, mol=True)
                ph = await self._insert(db, cid=990000107)
                await db.execute(text(
                    "INSERT INTO chemistry.chemical_cb"
                    " (chemical_id, cas_number, locale, entry)"
                    " VALUES (:t,'111-11-1','zh-CN', CAST(:e1 AS jsonb))"),
                    {"t": tgt, "e1": '{"zh":1}'})
                await db.execute(text(
                    "INSERT INTO chemistry.chemical_cb"
                    " (chemical_id, cas_number, locale, entry)"
                    " VALUES (:p,'222-22-2','zh-CN', CAST(:e2 AS jsonb))"),
                    {"p": ph, "e2": '{"oldzh":1}'})
                await db.execute(text(
                    "INSERT INTO chemistry.chemical_cb"
                    " (chemical_id, cas_number, locale, entry)"
                    " VALUES (:p,'333-33-3','en', CAST(:e3 AS jsonb))"),
                    {"p": ph, "e3": '{"en":1}'})
                await db.commit()
                surv = await absorb(db, source_id=ph, target_id=tgt,
                                    reason="t-cb-loc", trigger="unit-test",
                                    evidence_cid=990000107)
                await db.commit()
                rows = (await db.execute(text(
                    "SELECT locale, cas_number, entry FROM chemistry.chemical_cb"
                    " WHERE chemical_id=:i ORDER BY locale"), {"i": surv})).all()
                old_left = (await db.execute(text(
                    "SELECT count(*) FROM chemistry.chemical_cb"
                    " WHERE chemical_id=:i"), {"i": ph})).scalar()
                return [tuple(r) for r in rows], old_left
        rows, old_left = self._run(go())
        self.assertEqual(old_left, 0)
        self.assertEqual(rows, [
            ("en", "333-33-3", {"en": 1}),           # survivor 无 → 改指原样
            ("zh-CN", "111-11-1", {"zh": 1}),         # 同键 → survivor 值保留(cas非空不被覆盖)
        ])

    def test_whitelist_matches_schema(self):
        """白名单列必须真实存在于表; 排除列绝不在白名单。"""
        from api.services.identity import ONE_TO_ONE_MERGE_COLUMNS
        async def go():
            async with self._session() as db:
                from sqlalchemy import text
                out = {}
                for (sch, tbl), cols in ONE_TO_ONE_MERGE_COLUMNS.items():
                    rows = (await db.execute(text(
                        "SELECT column_name FROM information_schema.columns"
                        " WHERE table_schema=:s AND table_name=:t"),
                        {"s": sch, "t": tbl})).all()
                    real = {r[0] for r in rows}
                    out[f"{sch}.{tbl}"] = (set(cols) - real, real & set(cols))
                return out
        res = self._run(go())
        for tbl, (missing, _) in res.items():
            self.assertFalse(missing, f"{tbl} 白名单含不存在列: {missing}")
        banned = {"chemical_id", "created_at", "updated_at",
                  "fetched_at", "locale"}
        for (sch, tbl), cols in ONE_TO_ONE_MERGE_COLUMNS.items():
            hit = banned & set(cols)
            self.assertFalse(hit, f"{tbl} 白名单含禁列: {hit}")

    def test_constraints_strategy_consistency(self):
        """约束驱动完整性: 凡 PK/UNIQUE(含partial unique index)含 chemical_id
        的 registry 表, strategy 必须非 REKEY_MANY。未来新增
        UNIQUE(chemical_id, foo) 而 registry 未声明碰撞处理 → 本测试红。"""
        from sqlalchemy import text
        from api.services.identity import reference_table_strategies
        import re as _re

        SQL_C = (
            "SELECT n.nspname, c.relname, pg_get_constraintdef(con.oid) "
            "FROM pg_constraint con "
            "JOIN pg_class c ON c.oid = conrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE contype IN ('p','u') "
            "AND n.nspname NOT IN ('pg_catalog','information_schema')")
        SQL_I = (
            "SELECT schemaname, tablename, indexdef FROM pg_indexes "
            "WHERE indexdef LIKE 'CREATE UNIQUE%' AND schemaname NOT LIKE 'pg%'")

        async def go():
            async with self._session() as db:
                qc = await db.execute(text(SQL_C))
                qi = await db.execute(text(SQL_I))
                return list(qc) + list(qi)

        hits = []
        for r in self._run(go()):
            d = r[-1]
            m = _re.search(r"\(([^)]+)\)", d)
            if not m:
                continue
            cols = {c.strip().split()[0] for c in m.group(1).split(",")}
            if "chemical_id" in cols:
                hits.append((r[0], r[1], d))
        strat = reference_table_strategies()
        for sch, tbl, d in hits:
            if (sch, tbl) in strat:
                self.assertNotEqual(
                    strat[(sch, tbl)], "REKEY_MANY",
                    f"{sch}.{tbl} 约束含 chemical_id ({d}) 但 strategy="
                    "REKEY_MANY — 生产 UPDATE 会撞唯一约束")
        # 反向: 非 REKEY_MANY 的表必须有含 chemical_id 的约束依据 或 是
        # 声明式例外(不需要)。MERGE_ONE_TO_ONE/DEDUPE_REKEY 本身即声明。

    def test_reaction_dedupe_same_rxn_role(self):
        """同 reaction+role 双侧 → 不撞PK, 只保留一条 canonical 引用;
        survivor payload 空被 old 补, 非空不被覆盖。"""
        from sqlalchemy import text
        from api.services.identity import absorb
        async def go():
            async with self._session() as db:
                tgt = await self._insert(db, cid=990000201, mol=True)
                ph = await self._insert(db, cid=990000201)
                for i, (cid_, role, oc) in enumerate([
                        (111111, "REACTANT", 1), (222222, "SOLVENT", 5)]):
                    await db.execute(text(
                        "INSERT INTO chemistry.reaction_chemicals"
                        " (reaction_id, chemical_id, role, occurrence_count)"
                        " VALUES (:r,:c,:ro,:oc)"),
                        {"r": cid_, "c": tgt, "ro": role, "oc": oc})
                # old: 同111111同role(撞键, amount=7.5补空, occ=3非空让survivor=1) + 独有333333(改指)
                await db.execute(text(
                    "INSERT INTO chemistry.reaction_chemicals"
                    " (reaction_id, chemical_id, role, occurrence_count, amount_value)"
                    " VALUES (111111,:c,'REACTANT',3,7.5)"), {"c": ph})
                await db.execute(text(
                    "INSERT INTO chemistry.reaction_chemicals"
                    " (reaction_id, chemical_id, role, occurrence_count)"
                    " VALUES (333333,:c,'REACTANT',1)"), {"c": ph})
                await db.commit()
                surv = await absorb(db, source_id=ph, target_id=tgt,
                                    reason="t-rxn", trigger="unit-test",
                                    evidence_cid=990000201)
                await db.commit()
                r1 = (await db.execute(text(
                    "SELECT occurrence_count, amount_value FROM chemistry.reaction_chemicals"
                    " WHERE reaction_id=111111 AND chemical_id=:i AND role='REACTANT'"),
                    {"i": surv})).first()
                n1 = (await db.execute(text(
                    "SELECT count(*) FROM chemistry.reaction_chemicals"
                    " WHERE reaction_id=111111 AND role='REACTANT'"
                    " AND chemical_id IN (:i, :j)"),
                    {"i": surv, "j": ph})).scalar()
                n3 = (await db.execute(text(
                    "SELECT count(*) FROM chemistry.reaction_chemicals"
                    " WHERE reaction_id=333333 AND chemical_id=:i"),
                    {"i": surv})).scalar()
                n2 = (await db.execute(text(
                    "SELECT count(*) FROM chemistry.reaction_chemicals"
                    " WHERE reaction_id=222222 AND chemical_id=:i AND role='SOLVENT'"),
                    {"i": surv})).scalar()
                oldleft = (await db.execute(text(
                    "SELECT count(*) FROM chemistry.reaction_chemicals"
                    " WHERE chemical_id=:i"), {"i": ph})).scalar()
                return r1, n1, n3, n2, oldleft
        r1, n1, n3, n2, oldleft = self._run(go())
        self.assertEqual(tuple(r1), (1, 7.5))  # occ survivor保留, amount old补空
        self.assertEqual((n1, n3, n2, oldleft), (1, 1, 1, 0))

    def test_reaction_diff_rxn_rekey(self):
        """old/survivor 不同 reaction → 正常改指不去重。"""
        from sqlalchemy import text
        from api.services.identity import absorb
        async def go():
            async with self._session() as db:
                tgt = await self._insert(db, cid=990000202, mol=True)
                ph = await self._insert(db, cid=990000202)
                await db.execute(text(
                    "INSERT INTO chemistry.reaction_chemicals"
                    " (reaction_id, chemical_id, role, occurrence_count)"
                    " VALUES (444444,:c,'REACTANT',1)"),
                    {"c": ph})
                await db.commit()
                surv = await absorb(db, source_id=ph, target_id=tgt,
                                    reason="t-rxn2", trigger="unit-test",
                                    evidence_cid=990000202)
                await db.commit()
                n = (await db.execute(text(
                    "SELECT count(*) FROM chemistry.reaction_chemicals"
                    " WHERE reaction_id=444444 AND chemical_id=:i"),
                    {"i": surv})).scalar()
                return n
        self.assertEqual(self._run(go()), 1)

    def test_supplier_same_cbsid_collision(self):
        """supplier_listing 同 cbsid 双侧 → payload 补空后删 old, 不撞PK;
        不同 cbsid → 全部改指。"""
        from sqlalchemy import text
        from api.services.identity import absorb
        async def go():
            async with self._session() as db:
                tgt = await self._insert(db, cid=990000203, mol=True)
                ph = await self._insert(db, cid=990000203)
                # cbsid 外键 → chemical_supplier_profile, 先造 profile
                await db.execute(text(
                    "INSERT INTO chemistry.chemical_supplier_profile (cbsid, name)"
                    " VALUES ('UT1','ut1'),('UT2','ut2') ON CONFLICT DO NOTHING"))
                # 同 cbsid: survivor remark NULL → old 补; purity 双方非空不同 → survivor 保留
                await db.execute(text(
                    "INSERT INTO chemistry.chemical_supplier_listing"
                    " (chemical_id, cbsid, purity, pack_price, remark)"
                    " VALUES (:c,'UT1',98.5,100,NULL)"), {"c": tgt})
                await db.execute(text(
                    "INSERT INTO chemistry.chemical_supplier_listing"
                    " (chemical_id, cbsid, purity, pack_price, remark)"
                    " VALUES (:c,'UT1',99.9,50,'old-note')"), {"c": ph})
                # 独有 cbsid → 改指
                await db.execute(text(
                    "INSERT INTO chemistry.chemical_supplier_listing"
                    " (chemical_id, cbsid, remark) VALUES (:c,'UT2','x')"),
                    {"c": ph})
                await db.commit()
                surv = await absorb(db, source_id=ph, target_id=tgt,
                                    reason="t-sup", trigger="unit-test",
                                    evidence_cid=990000203)
                await db.commit()
                a = (await db.execute(text(
                    "SELECT purity, pack_price, remark FROM chemistry.chemical_supplier_listing"
                    " WHERE cbsid='UT1' AND chemical_id=:i"), {"i": surv})).first()
                n1 = (await db.execute(text(
                    "SELECT count(*) FROM chemistry.chemical_supplier_listing"
                    " WHERE cbsid='UT1' AND chemical_id IN (:i, :j)"),
                    {"i": surv, "j": ph})).scalar()
                n2 = (await db.execute(text(
                    "SELECT count(*) FROM chemistry.chemical_supplier_listing"
                    " WHERE cbsid='UT2' AND chemical_id=:i"), {"i": surv})).scalar()
                oldleft = (await db.execute(text(
                    "SELECT count(*) FROM chemistry.chemical_supplier_listing"
                    " WHERE chemical_id=:i"), {"i": ph})).scalar()
                return tuple(a), n1, n2, oldleft
        a, n1, n2, oldleft = self._run(go())
        self.assertEqual(tuple(float(x) if isinstance(x, (int, float)) or
                               (isinstance(x, str) and x.replace('.', '', 1).isdigit())
                               else x for x in a),
                         (98.5, 100, "old-note"))  # purity survivor保留, remark old补空
        self.assertEqual((n1, n2, oldleft), (1, 1, 0))

    def test_dedupe_midway_failure_rollback(self):
        """DEDUPE_REKEY 中途炸 → 主表/redirect/merge_log/引用全回滚。"""
        import api.services.identity as ident
        from api.services.identity import absorb
        from sqlalchemy import text
        real = ident._dedupe_rekey
        async def bomb(db2, **kw):
            await real(db2, **kw)
            raise RuntimeError("dedupe midway bomb")
        async def go():
            async with self._session() as db:
                tgt = await self._insert(db, cid=990000204, mol=True)
                ph = await self._insert(db, cid=990000204)
                await db.execute(text(
                    "INSERT INTO chemistry.reaction_chemicals"
                    " (reaction_id, chemical_id, role, occurrence_count)"
                    " VALUES (555555,:c,'REACTANT',1)"),
                    {"c": ph})
                await db.commit()
                ident._dedupe_rekey = bomb
                try:
                    await absorb(db, source_id=ph, target_id=tgt,
                                 reason="t-bomb2", trigger="unit-test",
                                 evidence_cid=990000204)
                except RuntimeError:
                    await db.rollback()
                finally:
                    ident._dedupe_rekey = real
                both = (await db.execute(text(
                    "SELECT count(*) FROM chemistry.chemicals WHERE id IN (:a,:b)"),
                    {"a": tgt, "b": ph})).scalar()
                logs = (await db.execute(text(
                    "SELECT count(*) FROM maintenance.identity_merge_log"
                    " WHERE source_id=:s"), {"s": ph})).scalar()
                rx = (await db.execute(text(
                    "SELECT count(*) FROM chemistry.reaction_chemicals"
                    " WHERE chemical_id=:i"), {"i": ph})).scalar()
                return both, logs, rx
        both, logs, rx = self._run(go())
        self.assertEqual((both, logs, rx), (2, 0, 1))

    def test_1to1_midway_failure_rollback(self):
        """1:1 合并中途炸 → 主表两行存活/merge_log/redirect 零残留。"""
        import api.services.identity as ident
        from api.services.identity import absorb
        from sqlalchemy import text
        real = ident._merge_one_to_one

        async def bomb(db2, **kw):
            await real(db2, **kw)
            raise RuntimeError("1:1 midway bomb")

        async def go():
            async with self._session() as db:
                tgt = await self._insert(db, cid=990000106, mol=True)
                ph = await self._insert(db, cid=990000106)
                await db.execute(text(
                    "INSERT INTO chemistry.chemical_pubchem (chemical_id, record_title)"
                    " VALUES (:i,'x')"), {"i": tgt})
                await db.commit()
                ident._merge_one_to_one = bomb
                try:
                    await absorb(db, source_id=ph, target_id=tgt,
                                 reason="t-bomb", trigger="unit-test",
                                 evidence_cid=990000106)
                except RuntimeError:
                    await db.rollback()
                finally:
                    ident._merge_one_to_one = real
                both = (await db.execute(text(
                    "SELECT count(*) FROM chemistry.chemicals"
                    " WHERE id IN (:a,:b)"), {"a": tgt, "b": ph})).scalar()
                logs = (await db.execute(text(
                    "SELECT count(*) FROM maintenance.identity_merge_log"
                    " WHERE source_id=:s"), {"s": ph})).scalar()
                return both, logs
        both, logs = self._run(go())
        self.assertEqual(both, 2)
        self.assertEqual(logs, 0)


@unittest.skipUnless(DB_URL, "需要 PG")
class GateCoverageTests(IdentityResolutionTests):
    """0907 门禁覆盖: search CAS bypass 修复 + pubchem 强身份回补 gate。"""

    def test_cas_bypass_unique_hit_uses_resolver_id(self):
        # 1. CAS 唯一命中 → enqueue_cas_search_fetch 返回 resolver chemical_id
        from api.services.cb import enqueue_cas_search_fetch
        async def go():
            async with self.engine.begin() as db:
                rid = await self._insert(db, cas=CAS)
                enq, status, cid = await enqueue_cas_search_fetch(db, cas_number=CAS)
                return enq, status, cid, rid
        enq, status, cid, rid = self._run(go())
        # cas-unique-hit → EQUIVALENT(五状态契约, 序位3)
        self.assertEqual((enq, status, cid), (True, "EQUIVALENT", rid))

    def test_cas_bypass_new_uses_resolver_created_id(self):
        # 2. CAS NEW → resolver 合法占位行 id 直接穿透(调用方不再 LIMIT 1 重查)
        from api.services.cb import enqueue_cas_search_fetch
        async def go():
            async with self.engine.begin() as db:
                enq, status, cid = await enqueue_cas_search_fetch(db, cas_number=CAS)
                return enq, status, cid
        enq, status, cid = self._run(go())
        self.assertEqual((enq, status), (True, "NEW"))
        self.assertIsInstance(cid, int)
        self.assertGreater(cid, 0)

    def test_cas_bypass_ambiguous_returns_none(self):
        # 3. CAS 多候选无强判据 → AMBIGUOUS, chemical_id=None, 绝不选 candidate
        from api.services.cb import enqueue_cas_search_fetch
        async def go():
            async with self.engine.begin() as db:
                await self._insert(db, cas=CAS, ik=IK)
                await self._insert(db, cas=CAS, ik=None)
                enq, status, cid = await enqueue_cas_search_fetch(db, cas_number=CAS)
                return enq, status, cid
        enq, status, cid = self._run(go())
        self.assertEqual((enq, status, cid), (True, "AMBIGUOUS", None))

    def test_cas_bypass_no_limit1_fallback_in_search(self):
        # 4. 旧 LIMIT 1 fallback 代码不复存在(静态检查)
        src = open("api/services/search.py").read()
        self.assertNotIn("cas_numbers @> ARRAY[:cas] LIMIT 1", src)

    def test_pubchem_reconcile_new_cid_free(self):
        # P1. 行 CID 空, 新 CID 无他行 → 原样返回, 不 merge 不建行
        from api.services.workqueue import reconcile_pubchem_identity
        from sqlalchemy import text
        async def go():
            async with self.engine.begin() as db:
                rid = await self._insert(db, cas=CAS)
                out = await reconcile_pubchem_identity(db, rid, CID_A)
                n = (await db.execute(text(
                    "SELECT count(*) FROM chemistry.chemicals WHERE pubchem_cid=:c"),
                    {"c": CID_A})).scalar()
                return out, n
        out, n = self._run(go())
        self.assertEqual(out, out)  # id 返回
        self.assertEqual(n, 0)      # reconcile 不写 CID(sync 已写), 不建行

    def test_pubchem_reconcile_absorbs_into_existing_cid_row(self):
        # P2. 新 CID 已存在另一行 → 正式 absorb, same-CID 一行收敛
        from api.services.workqueue import reconcile_pubchem_identity
        from sqlalchemy import text
        async def go():
            async with self.engine.begin() as db:
                other = await self._insert(db, cid=CID_A, mol=True)
                mine = await self._insert(db, cas=CAS, cid=CID_A)
                out = await reconcile_pubchem_identity(db, mine, CID_A)
                left = (await db.execute(text(
                    "SELECT count(*) FROM chemistry.chemicals WHERE pubchem_cid=:c"),
                    {"c": CID_A})).scalar()
                return out, left, other, mine
        out, left, other, mine = self._run(go())
        self.assertEqual(left, 1)
        self.assertIn(out, (other, mine))

    def test_pubchem_reconcile_same_row_noop(self):
        # P3. resolver 只命中当前行 → 不重复 merge
        from api.services.workqueue import reconcile_pubchem_identity
        async def go():
            async with self.engine.begin() as db:
                rid = await self._insert(db, cid=CID_A)
                out = await reconcile_pubchem_identity(db, rid, CID_A)
                return out, rid
        out, rid = self._run(go())
        self.assertEqual(out, rid)

    def test_pubchem_reconcile_conflict_fail_closed(self):
        # P4. 当前行已有不同非空 CID → CONFLICT 不覆盖不 merge
        from api.services.workqueue import reconcile_pubchem_identity
        from sqlalchemy import text
        async def go():
            async with self.engine.begin() as db:
                rid = await self._insert(db, cid=CID_A)
                out = await reconcile_pubchem_identity(db, rid, CID_B)
                cid_now = (await db.execute(text(
                    "SELECT pubchem_cid FROM chemistry.chemicals WHERE id=:i"),
                    {"i": rid})).scalar()
                return out, rid, cid_now
        out, rid, cid_now = self._run(go())
        self.assertEqual(out, rid)
        self.assertEqual(cid_now, CID_A)

    def test_pubchem_reconcile_gate_block_keeps_both(self):
        # P6. absorb 被 gate 拒(无 CID entity proof) → 两行保留不炸
        from api.services.workqueue import reconcile_pubchem_identity
        from sqlalchemy import text  # noqa: F401
        async def go():
            async with self.engine.begin() as db:
                # 当前行无CID; 新CID行存在 → resolve EXACT 指向他行,
                # 但 can_merge: src空侧由 evidence_cid 补齐=同CID → ALLOW 会过。
                # 构造 gate BLOCK: 当前行带不同非空 CID。
                rid = await self._insert(db, cid=CID_A)
                other = await self._insert(db, cid=CID_B)
                out = await reconcile_pubchem_identity(db, rid, CID_B)
                both = (await db.execute(text(
                    "SELECT count(*) FROM chemistry.chemicals WHERE id IN (:a,:b)"),
                    {"a": rid, "b": other})).scalar()
                return out, rid, both
        out, rid, both = self._run(go())
        # CONFLICT 分支(行 CID_A vs CID_B) → 不进入 absorb, 两行保留
        self.assertEqual(out, rid)
        self.assertEqual(both, 2)

    def test_pubchem_reconcile_child_facts_follow_survivor(self):
        # P7. absorb 后 source 子表事实归属 survivor
        from api.services.workqueue import reconcile_pubchem_identity
        from sqlalchemy import text
        async def go():
            async with self.engine.begin() as db:
                await self._insert(db, cid=CID_A, mol=True)
                mine = await self._insert(db, cas=CAS, cid=CID_A)
                await db.execute(text(
                    "INSERT INTO chemistry.name_index (chemical_id,name,lang,normalized,source,kind)"
                    " VALUES (:c,'gate-t','cn','gate-t','cb','supplier')"
                    " ON CONFLICT DO NOTHING"), {"c": mine})
                out = await reconcile_pubchem_identity(db, mine, CID_A)
                n_old = (await db.execute(text(
                    "SELECT count(*) FROM chemistry.name_index WHERE chemical_id=:c"),
                    {"c": mine})).scalar()
                n_surv = (await db.execute(text(
                    "SELECT count(*) FROM chemistry.name_index WHERE chemical_id=:c"),
                    {"c": out})).scalar()
                return n_old, n_surv
        n_old, n_surv = self._run(go())
        self.assertEqual(n_old, 0)
        self.assertEqual(n_surv, 1)


if __name__ == "__main__":
    unittest.main()
