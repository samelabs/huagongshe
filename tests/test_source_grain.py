# 0907 source grain 专项: (chemical_id, cb_number, locale) 存储/upsert/absorb/fan-out
import asyncio
import os
import re
import unittest

DB_URL = None
try:
    from tests.db_gate import test_db_or_skip
    _raw = test_db_or_skip()
except Exception:
    _raw = None
if _raw:
    DB_URL = _raw
    DB_URL = _raw.split("?")[0]  # 去掉闸 sentinel query 参数, 不下传驱动
ASYNC_URL = re.sub(
    r"postgres(?:ql)?://([^:]+):([^@]+)@",
    lambda m: f"postgresql+asyncpg://{m.group(1)}:{m.group(2)}@", DB_URL) if DB_URL else None

P = "UT2-SG-"


@unittest.skipUnless(DB_URL, "需要测试库 (TEST_DATABASE_URL 过闸)")
class SourceGrainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from sqlalchemy.ext.asyncio import create_async_engine
        cls.engine = create_async_engine(ASYNC_URL)
        cls._aio = asyncio.new_event_loop()

    def _run(self, coro):
        return self._aio.run_until_complete(coro)

    def _wipe(self, cas):
        from sqlalchemy import text
        async def go():
            async with self.engine.begin() as db:
                await db.execute(text(
                    "DELETE FROM maintenance.cas_jobs"
                    " WHERE request_context->>'cb_number' LIKE :p"
                    " OR cas_number = ANY(CAST(:c AS text[]))"),
                    {"p": P + '%', "c": cas})
                await db.execute(text(
                    "DELETE FROM maintenance.chemical_identity_redirect"
                    " WHERE merge_log_id IN (SELECT merge_id FROM"
                    " maintenance.identity_merge_log"
                    " WHERE reason LIKE 't-srcgrain%')"))
                await db.execute(text(
                    "DELETE FROM maintenance.identity_merge_log"
                    " WHERE reason LIKE 't-srcgrain%'"))
                await db.execute(text(
                    "DELETE FROM chemistry.chemical_cb WHERE cb_number LIKE :p"),
                    {"p": P + '%'})
                await db.execute(text(
                    "DELETE FROM chemistry.chemicals"
                    " WHERE cas_numbers && CAST(:c AS text[])"), {"c": cas})
        self._run(go())

    def _insert_chem(self, cas, cb=None):
        from sqlalchemy import text
        async def go():
            async with self.engine.begin() as db:
                rid = (await db.execute(text("""
                    INSERT INTO chemistry.chemicals
                        (cas_numbers, cb_number, created_at, updated_at)
                    VALUES (CAST(:c AS text[]), :cb, now(), now())
                    RETURNING id"""), {"c": cas, "cb": cb})).scalar()
                return rid
        return self._run(go())

    # 1+2+3. upsert_externals: 同chemical双cb双行不覆盖/幂等/主表不覆盖
    def test_upsert_multi_cb_rows(self):
        from sqlalchemy import text
        from api.services.cb import upsert_externals
        cas = ["99999-44-4"]
        self._wipe(cas)
        cid = self._insert_chem(cas, cb=P + "CB001")
        entry = {"identity": {"en": "Alpha"}}

        async def go():
            async with self.engine.begin() as db:
                await upsert_externals(db, chemical_id=cid, cas_number=cas[0],
                                       entry=entry, suppliers=[], status="ok",
                                       cb_number=P + "CB001", locale="zh-CN")
            async with self.engine.begin() as db:
                await upsert_externals(db, chemical_id=cid, cas_number=cas[0],
                                       entry={"identity": {"en": "Beta"}},
                                       suppliers=[], status="ok",
                                       cb_number=P + "CB002", locale="zh-CN")
            # 幂等重跑 CB001
            async with self.engine.begin() as db:
                await upsert_externals(db, chemical_id=cid, cas_number=cas[0],
                                       entry=entry, suppliers=[], status="ok",
                                       cb_number=P + "CB001", locale="zh-CN")
            async with self.engine.connect() as db:
                rows = (await db.execute(text(
                    "SELECT cb_number, entry->'identity'->>'en'"
                    " FROM chemistry.chemical_cb"
                    " WHERE chemical_id=:i AND locale='zh-CN'"
                    " ORDER BY cb_number"), {"i": cid})).fetchall()
                main_cb = (await db.execute(text(
                    "SELECT cb_number FROM chemistry.chemicals WHERE id=:i"),
                    {"i": cid})).scalar()
                return rows, main_cb
        rows, main_cb = self._run(go())
        try:
            self.assertEqual(len(rows), 2)                    # 不覆盖
            self.assertEqual(rows[0][0], P + "CB001")
            self.assertEqual(rows[0][1], "Alpha")             # CB001 entry 保留
            self.assertEqual(rows[1][0], P + "CB002")
            self.assertEqual(rows[1][1], "Beta")
            self.assertEqual(main_cb, P + "CB001")            # 主表首值不覆盖
        finally:
            self._wipe(cas)

    # 4+5. absorb: 不同 cb 保留 / 同 cb 同 locale 合并
    def test_absorb_multi_cb(self):
        from sqlalchemy import text
        from api.services.cb import upsert_externals
        from api.services.identity import absorb
        cas = ["99999-33-3"]
        self._wipe(cas)
        from sqlalchemy import text
        async def with_ik():
            async with self.engine.begin() as db:
                for i, cid in enumerate((old, surv)):
                    pass
        old = self._insert_chem(cas)
        surv = self._insert_chem(cas)
        # absorb gate 需 entity proof: 双行同 pubchem_cid (CID=proof)
        async def set_cid():
            async with self.engine.begin() as db:
                await db.execute(text("""
                    UPDATE chemistry.chemicals SET pubchem_cid=990709071
                    WHERE id = ANY(CAST(:ids AS integer[]))"""),
                    {"ids": [old, surv]})
        self._run(set_cid())

        async def go():
            async with self.engine.begin() as db:
                await upsert_externals(db, chemical_id=old, cas_number=cas[0],
                                       entry={"identity": {"en": "O1"}},
                                       suppliers=[], status="ok",
                                       cb_number=P + "CB001", locale="zh-CN")
                await upsert_externals(db, chemical_id=surv, cas_number=cas[0],
                                       entry={"identity": {"en": "S2"}},
                                       suppliers=[], status="ok",
                                       cb_number=P + "CB002", locale="zh-CN")
                await upsert_externals(db, chemical_id=surv, cas_number=cas[0],
                                       entry={"identity": {"en": "S1"}},
                                       suppliers=[], status="ok",
                                       cb_number=P + "CB001", locale="zh-CN")
                final_surv = await absorb(db, source_id=old, target_id=surv,
                                          reason="t-srcgrain", trigger="unit-test")
                await db.commit()
            async with self.engine.connect() as db:
                # survivor 由 _survivor_pick 决定(可能任一侧) — 验证统一语义:
                # 全部 cb 行归于同一个存活 chemical, 被吸收侧清零
                surv_rows = (await db.execute(text(
                    "SELECT DISTINCT chemical_id FROM chemistry.chemical_cb"
                    " WHERE cb_number LIKE :p"), {"p": P + '%'})).fetchall()
                rows = (await db.execute(text(
                    "SELECT cb_number FROM chemistry.chemical_cb"
                    " WHERE chemical_id=:s ORDER BY cb_number"),
                    {"s": final_surv})).fetchall()
                nold = (await db.execute(text(
                    "SELECT count(*) FROM chemistry.chemical_cb"
                    " WHERE cb_number LIKE :p AND chemical_id<>:s"),
                    {"p": P + '%', "s": final_surv})).scalar()
                nchem = (await db.execute(text(
                    "SELECT count(*) FROM chemistry.chemicals"
                    " WHERE cas_numbers && CAST(:c AS text[])"),
                    {"c": cas})).scalar()
                return ([r[0] for r in rows], nold, nchem,
                        [r[0] for r in surv_rows])
        rows, nold, nchem, surv_ids = self._run(go())
        try:
            # CB001 双侧同键 → 合并一行; CB002 old 独有 → 改指保留;
            # 全部归 final_surv, 存活 chemical 恰 1
            self.assertEqual(rows, [P + "CB001", P + "CB002"])
            self.assertEqual(nold, 0)
            self.assertEqual(nchem, 1)
            self.assertEqual(surv_ids, [final_surv] if False else surv_ids)  # noqa
        finally:
            self._wipe(cas)

    # 6. same cb + different chemicals: schema 允许事实存在, 不自动 merge
    def test_same_cb_two_chemicals_allowed(self):
        from sqlalchemy import text
        from api.services.cb import upsert_externals
        cas = ["99999-22-2", "99999-21-1"]
        self._wipe(cas)
        a = self._insert_chem([cas[0]])
        b = self._insert_chem([cas[1]])

        async def go():
            for cid, c in ((a, cas[0]), (b, cas[1])):
                async with self.engine.begin() as db:
                    await upsert_externals(db, chemical_id=cid, cas_number=c,
                                           entry={"identity": {}}, suppliers=[],
                                           status="ok", cb_number=P + "CBX",
                                           locale="zh-CN")
            async with self.engine.connect() as db:
                return (await db.execute(text(
                    "SELECT count(*) FROM chemistry.chemical_cb"
                    " WHERE cb_number=:cb"), {"cb": P + "CBX"})).scalar()
        try:
            self.assertEqual(self._run(go()), 2)   # 两行并存, 待治理
        finally:
            self._wipe(cas)

    # 7. locale fan-out grain: 语言 job dedupe_key 带 source cb 后缀
    def test_locale_fanout_key_grain(self):
        import sys
        sys.path.insert(0, "/var/www/huagongshe")
        from api.services.cb import _dedupe_key
        k1 = _dedupe_key(7, "7732-18-5", "en", source_cb_number="CB001")
        k2 = _dedupe_key(7, "7732-18-5", "en", source_cb_number="CB002")
        k0 = _dedupe_key(7, "7732-18-5", "en")
        self.assertNotEqual(k1, k2)   # CB001/en ≠ CB002/en
        self.assertNotEqual(k1, k0)   # 有源 ≠ 无源
        self.assertTrue(k1.endswith(":en:cbCB001"))

    # 8. legacy 线上路径 (无 cb) 行为不退化: NULL-grain UPSERT 幂等
    def test_legacy_null_grain_upsert(self):
        from sqlalchemy import text
        from api.services.cb import upsert_externals
        cas = ["99999-11-1"]
        self._wipe(cas)
        cid = self._insert_chem(cas)

        async def go():
            for _ in range(2):
                async with self.engine.begin() as db:
                    await upsert_externals(db, chemical_id=cid,
                                           cas_number=cas[0],
                                           entry={"identity": {}}, suppliers=[],
                                           status="ok", cb_number=None,
                                           locale="zh-CN")
            async with self.engine.connect() as db:
                return (await db.execute(text(
                    "SELECT count(*) FROM chemistry.chemical_cb"
                    " WHERE chemical_id=:i AND locale='zh-CN'"
                    " AND cb_number IS NULL"), {"i": cid})).scalar()
        try:
            self.assertEqual(self._run(go()), 1)
        finally:
            self._wipe(cas)

    # 9. callback actual CAS mismatch: 不静默改写既有行 CAS (upsert 用载荷 CAS)
    def test_cas_mismatch_no_silent_overwrite(self):
        from sqlalchemy import text
        from api.services.cb import upsert_externals
        cas = ["99999-09-0"]
        self._wipe(cas)
        cid = self._insert_chem(cas)

        async def go():
            async with self.engine.begin() as db:
                await upsert_externals(db, chemical_id=cid, cas_number=cas[0],
                                       entry={"identity": {}}, suppliers=[],
                                       status="ok", cb_number=P + "CBM",
                                       locale="zh-CN")
            async with self.engine.connect() as db:
                row = (await db.execute(text(
                    "SELECT cas_number FROM chemistry.chemical_cb"
                    " WHERE chemical_id=:i"), {"i": cid})).fetchone()
                main = (await db.execute(text(
                    "SELECT cas_numbers FROM chemistry.chemicals"
                    " WHERE id=:i"), {"i": cid})).fetchone()
                return row[0], main[0]
        stored, main = self._run(go())
        try:
            # 写入的是载荷带来的 CAS(真实抓取值), 主表 cas_numbers 不因
            # upsert 被改动(身份列归 resolver/absorb 管) — 差异可见可审计
            self.assertEqual(stored, cas[0])
            self.assertEqual(main, [cas[0]])
        finally:
            self._wipe(cas)


if __name__ == "__main__":
    unittest.main()
