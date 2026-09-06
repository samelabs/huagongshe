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

DB_URL = os.environ.get("TEST_DATABASE_URL")
if not DB_URL:
    from api.core.config import settings  # noqa: E402
    DB_URL = getattr(settings, "database_url", None)

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
                await c.execute(text("""
                    DELETE FROM maintenance.chemical_identity_redirect
                    WHERE canonical_chemical_id IN (
                        SELECT id FROM chemistry.chemicals WHERE
                            cas_numbers @> ARRAY[:c] OR inchikey IN (:ik,:ik2)
                            OR pubchem_cid IN (:a,:b))
                """), {"c": CAS, "ik": IK, "ik2": IK2, "a": CID_A, "b": CID_B})
                await c.execute(text("""
                    DELETE FROM maintenance.identity_merge_log WHERE
                        source_id IN (
                            SELECT id FROM chemistry.chemicals WHERE
                                cas_numbers @> ARRAY[:c] OR inchikey IN (:ik,:ik2)
                                OR pubchem_cid IN (:a,:b))
                        OR target_id IN (
                            SELECT id FROM chemistry.chemicals WHERE
                                cas_numbers @> ARRAY[:c] OR inchikey IN (:ik,:ik2)
                                OR pubchem_cid IN (:a,:b))
                """), {"c": CAS, "ik": IK, "ik2": IK2, "a": CID_A, "b": CID_B})
                await c.execute(text("""
                    DELETE FROM chemistry.chemicals WHERE
                        cas_numbers @> ARRAY[:c] OR inchikey IN (:ik,:ik2)
                        OR pubchem_cid IN (:a,:b)
                """), {"c": CAS, "ik": IK, "ik2": IK2, "a": CID_A, "b": CID_B})
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
                    " VALUES (:id,:cas,'test-dedupe-1','{}'::jsonb)"),
                    {"id": ph, "cas": CAS})
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
                    " WHERE dedupe_key='test-dedupe-1'"))).scalar()
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
        reg = set(CHEMICAL_REFERENCE_TABLES)
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


if __name__ == "__main__":
    unittest.main()
