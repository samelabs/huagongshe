"""I-061 CAS 校验位 + I-026 在途 cas_job 详情态 — 针对性测试。

I-061:
1. valid_cas/cas_checkdigit_valid 纯函数正反例;
2. 搜索入口: 校验位正确照常检索; 校验位错误 → SearchError(invalid_cas,
   "CAS 号校验位不正确") 且不建行;
3. cb.py upsert: 校验位错误的 CAS 不追加进主表 cas_numbers, 正常的照加。

I-026:
4. cb_row=None 且无在途 cas_job → cb state none(absent);
   有 queued/leased job → queued; error(失败终态)不算在途。

直调函数 + 真链测试库; 哨兵化合物挂高位 id, 出测试即清。
"""
from __future__ import annotations

import asyncio
import os
import re
import unittest
from urllib.parse import parse_qs, urlparse

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.db_gate import require_test_db  # I-058: 收口到统一闸(原内联 sentinel 等价)
try:
    DB_URL = require_test_db().split("?", 1)[0]
except Exception:
    DB_URL = ""

_GATE = unittest.skipUnless(DB_URL, "需要 PG 测试库 (TEST_DATABASE_URL 过闸)")

# 1000000-00-9: 9 位 body 反转后 1×9=9 → 校验位 9, 合法且大概率未收录
VALID_UNLISTED_CAS = "1000000-00-9"
# 50-00-9: 甲醛 50-00-0 的校验位被改错(50-00-0 的 0 才是对的)
INVALID_CAS = "50-00-9"

SETUP_SQL = """
INSERT INTO chemistry.chemicals
  (id, smiles, molecular_formula, average_mass, monoisotopic_mass,
   inchikey, mol, morgan_bfp, morgan_sfp, preferred_name, iupac_name, created_at, updated_at)
VALUES
  (:id, 'CCO', 'C2H6O', 46.07, 46.0419, 'LFQSCWFLJHTTHZ-UHFFFAOYSA-N',
   mol_from_smiles('CCO'), morganbv_fp(mol_from_smiles('CCO')), morgan_fp(mol_from_smiles('CCO')),
   '校验位哨兵', 'cas-checkdigit-sentinel', now(), now())
ON CONFLICT (id) DO UPDATE SET preferred_name='校验位哨兵', iupac_name='cas-checkdigit-sentinel'
"""


def _engine():
    from sqlalchemy.pool import NullPool
    url = DB_URL.split("?")[0]
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url.split("://", 1)[1]
    return create_async_engine(url, poolclass=NullPool)


async def _alloc_sentinel_id(conn) -> int:
    row = (await conn.execute(text(
        "SELECT greatest(coalesce(max(id),0), 100000000) + 1 FROM chemistry.chemicals"
    ))).scalar()
    sid = int(row)
    await conn.execute(text(
        "DELETE FROM maintenance.cas_jobs WHERE chemical_id=:i"), {"i": sid})
    await conn.execute(text(
        "DELETE FROM chemistry.chemical_cb WHERE chemical_id=:i"), {"i": sid})
    await conn.execute(text(
        "DELETE FROM chemistry.name_index WHERE chemical_id=:i"), {"i": sid})
    await conn.execute(text(SETUP_SQL), {"id": sid})
    return sid


class CasCheckdigitPureTests(unittest.TestCase):
    """I-061 纯函数: 不需要 DB。"""

    def test_known_good_cas(self):
        from api.chemistry import valid_cas
        for cas in ("50-00-0", "64-17-5", "67-64-1", "7732-18-5", "77-78-1"):
            self.assertTrue(valid_cas(cas), cas)

    def test_bad_checkdigit_rejected(self):
        from api.chemistry import valid_cas
        for cas in ("50-00-9", "64-17-6", "7732-18-6", INVALID_CAS):
            self.assertFalse(valid_cas(cas), cas)

    def test_bad_format_rejected(self):
        from api.chemistry import valid_cas
        for cas in ("50000-0", "50-000-0", "abc-00-0", "", None, "12345678-00-0"):
            self.assertFalse(valid_cas(cas), repr(cas))


@_GATE
class CasCheckdigitSearchEntryTests(unittest.TestCase):
    def run_coro(self, coro):
        return asyncio.run(coro)

    def test_search_entry_rejects_bad_checkdigit_without_creating_rows(self):
        from api.services.search import INVALID_CAS, SearchError, execute_search

        async def body():
            eng = _engine()
            sid = None
            try:
                # 哨兵行带合法冷门 CAS: 检索命中本行, 不触发 CAS-miss 入队,
                # 也不会撞到 redis 搜索缓存里的历史结果。
                async with eng.begin() as conn:
                    sid = await _alloc_sentinel_id(conn)
                    await conn.execute(text("""
                        UPDATE chemistry.chemicals
                        SET cas_numbers=ARRAY[:cas] WHERE id=:i
                    """), {"cas": VALID_UNLISTED_CAS, "i": sid})
                async with eng.connect() as conn:
                    result = await execute_search(
                        conn, VALID_UNLISTED_CAS, "exact",
                        threshold=0.7, page=1, page_size=10, actor_id=None)
                    chemicals = result["chemicals"]
                return sid, chemicals
            finally:
                if sid is not None:
                    async with eng.begin() as conn:
                        await conn.execute(text(
                            "DELETE FROM chemistry.chemicals WHERE id=:i"), {"i": sid})
                await eng.dispose()

        sid, chemicals = self.run_coro(body())
        self.assertEqual(
            [row["id"] for row in chemicals], [sid],
            "校验位正确的 CAS 照常检索并命中",
        )

        bad_cas = "1000000-00-7"  # 同 body 校验位改错

        async def body_bad():
            eng = _engine()
            try:
                async with eng.connect() as conn:
                    await execute_search(
                        conn, bad_cas, "exact",
                        threshold=0.7, page=1, page_size=10, actor_id=None)
            finally:
                await eng.dispose()

        with self.assertRaises(Exception) as raised:
            self.run_coro(body_bad())
        self.assertIsInstance(raised.exception, SearchError)
        self.assertEqual(raised.exception.kind, INVALID_CAS)
        self.assertEqual(raised.exception.detail, "CAS 号校验位不正确")

        async def body_no_row():
            eng = _engine()
            try:
                async with eng.connect() as conn:
                    return (await conn.execute(text("""
                        SELECT count(*) FROM chemistry.chemicals
                        WHERE cas_numbers @> ARRAY[:cas]
                    """), {"cas": bad_cas})).scalar()
            finally:
                await eng.dispose()

        self.assertEqual(self.run_coro(body_no_row()), 0, "校验位错误不得建行")

    def test_cb_upsert_does_not_append_bad_checkdigit_cas(self):
        from api.services.cb import upsert_externals

        async def body():
            eng = _engine()
            try:
                async with eng.begin() as conn:
                    sid = await _alloc_sentinel_id(conn)
                entry = {"identity": {"cn": "校验位哨兵名", "en": "Sentinel", "formula": "C2H6O"}}
                for cas in (INVALID_CAS, "50-00-0"):
                    async with eng.begin() as conn:
                        await upsert_externals(
                            conn, chemical_id=sid, cas_number=cas,
                            entry=entry, suppliers=[],
                            status="ok", cb_number=f"CBCAS{cas[-1]}", locale="zh-CN")
                async with eng.begin() as conn:
                    nums = (await conn.execute(text(
                        "SELECT cas_numbers FROM chemistry.chemicals WHERE id=:i"
                    ), {"i": sid})).scalar()
                    await conn.execute(text(
                        "DELETE FROM chemistry.chemical_cb WHERE chemical_id=:i"), {"i": sid})
                    await conn.execute(text(
                        "DELETE FROM chemistry.chemicals WHERE id=:i"), {"i": sid})
                return sid, nums
            finally:
                await eng.dispose()

        sid, nums = self.run_coro(body())
        self.assertIn("50-00-0", list(nums or []))
        self.assertNotIn(INVALID_CAS, list(nums or []))


@_GATE
class CasJobPendingDetailTests(unittest.TestCase):
    """I-026: cb_row=None 时在途 cas_job → queued, 否则 absent(none)。"""

    def run_coro(self, coro):
        return asyncio.run(coro)

    def _detail(self, sid):
        from api.services.chemicals import get_chemical_detail

        async def body():
            eng = _engine()
            try:
                async with eng.connect() as conn:
                    result = await get_chemical_detail(
                        conn, sid, actor_id=None, priority=50, enrich="full")
                    return result["enrichment"]["sources"]["cb"]
            finally:
                await eng.dispose()

        return self.run_coro(body())

    def test_absent_without_pending_job_and_queued_with(self):
        from api.services.chemicals import get_chemical_detail

        async def prep(status: str | None):
            eng = _engine()
            try:
                async with eng.begin() as conn:
                    sid = await _alloc_sentinel_id(conn)
                    await conn.execute(text("""
                        UPDATE chemistry.chemicals
                        SET cas_numbers=ARRAY[:cas] WHERE id=:i
                    """), {"cas": VALID_UNLISTED_CAS, "i": sid})
                    if status is not None:
                        await conn.execute(text("""
                            INSERT INTO maintenance.cas_jobs
                              (chemical_id,cas_number,status,dedupe_key)
                            VALUES (:i,:cas,:status,:dk)
                        """), {
                            "i": sid, "cas": VALID_UNLISTED_CAS, "status": status,
                            "dk": f"test-pending-{sid}",
                        })
                return sid
            finally:
                await eng.dispose()

        async def cleanup(sid: int):
            eng = _engine()
            try:
                async with eng.begin() as conn:
                    await conn.execute(text(
                        "DELETE FROM maintenance.cas_jobs WHERE chemical_id=:i"), {"i": sid})
                    await conn.execute(text(
                        "DELETE FROM chemistry.chemical_cb WHERE chemical_id=:i"), {"i": sid})
                    await conn.execute(text(
                        "DELETE FROM chemistry.name_index WHERE chemical_id=:i"), {"i": sid})
                    await conn.execute(text(
                        "DELETE FROM chemistry.chemicals WHERE id=:i"), {"i": sid})
            finally:
                await eng.dispose()

        # 无在途 job → absent 归一为 none
        sid_absent = self.run_coro(prep(None))
        try:
            self.assertEqual(self._detail(sid_absent), "none")
        finally:
            self.run_coro(cleanup(sid_absent))

        # queued job → queued(详情页提示获取中)
        sid_q = self.run_coro(prep("queued"))
        try:
            self.assertEqual(self._detail(sid_q), "queued")
        finally:
            self.run_coro(cleanup(sid_q))

        # leased(已被 worker 领走)同样算在途
        sid_l = self.run_coro(prep("leased"))
        try:
            self.assertEqual(self._detail(sid_l), "queued")
        finally:
            self.run_coro(cleanup(sid_l))

        # error 是失败终态, 不算在途 → 仍 none
        sid_e = self.run_coro(prep("error"))
        try:
            self.assertEqual(self._detail(sid_e), "none")
        finally:
            self.run_coro(cleanup(sid_e))


if __name__ == "__main__":
    unittest.main()
