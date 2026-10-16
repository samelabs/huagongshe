"""合并后的旧 HCID 详情返回 404 —— 现行裁定的专项锁定。

身份合并（absorb）删除旧行并落 redirect 记录；详情读取链（routes →
get_chemical_detail）不跟随 redirect。这是有意裁定：对外身份语义是
「旧编号已不存在」，不是「旧编号 301 到新编号」。本测试锁死三件事：
① 旧 HCID 详情抛 ChemicalNotFoundError（HTTP 404）
② survivor 详情正常（同一次合并的对照面）
③ 旧 id 的 redirect 记录确在、canonicalize_id 可解析（身份历史不丢，
   供 discovery/workapi 等内部链路使用）
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB_URL = None
try:
    from tests.db_gate import test_db_or_skip  # noqa: E402
    DB_URL = test_db_or_skip()
except Exception:  # noqa: BLE001 — 闸缺失/不合规都视为无测试库
    DB_URL = None

if DB_URL:
    DB_URL = DB_URL.split("?", 1)[0]
    if not DB_URL.startswith("postgresql+asyncpg://"):
        DB_URL = "postgresql+asyncpg://" + DB_URL.split("://", 1)[1]

# 测试专用标记值 — 与真实数据不可能相撞（与 test_identity 同段位）
CAS = "99999-99-9"
CID = 990000901


@unittest.skipUnless(DB_URL, "需要 PG 测试库")
class MergedOldIdReturns404Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import asyncio
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
        from sqlalchemy.pool import NullPool
        cls.engine = create_async_engine(DB_URL, poolclass=NullPool)
        cls._session = async_sessionmaker(cls.engine, expire_on_commit=False)
        cls._aio = asyncio.new_event_loop()
        asyncio.set_event_loop(cls._aio)

    @classmethod
    def tearDownClass(cls):
        cls._aio.run_until_complete(cls.engine.dispose())
        cls._aio.close()

    def _run(self, coro):
        return self._aio.run_until_complete(coro)

    async def _insert(self, db, *, cid=None, mol_text=None):
        from sqlalchemy import text
        rid = (await db.execute(text(
            "INSERT INTO chemistry.chemicals (created_at, updated_at, cas_numbers, pubchem_cid) "
            "VALUES (now(), now(), :cas, :cid) RETURNING id"),
            {"cas": [CAS], "cid": cid})).scalar_one()
        if mol_text:
            await db.execute(text(
                "UPDATE chemistry.chemicals SET mol=mol_from_ctab(:m) WHERE id=:id"),
                {"m": mol_text, "id": rid})
        return rid

    def test_merged_old_hcid_detail_404_survivor_ok_redirect_kept(self):
        from sqlalchemy import text
        from api.services.identity import absorb, canonicalize_id
        from api.services.chemicals import get_chemical_detail, ChemicalNotFoundError

        import tests.test_identity as ti
        mol = ti.TEST_MOL  # 苯甲酸：两侧同结构同 CID → 合并闸放行

        async def go():
            async with self._session() as db:
                tgt = await self._insert(db, cid=CID, mol_text=mol)
                old = await self._insert(db, cid=CID, mol_text=mol)
                await db.commit()
                survivor = await absorb(db, source_id=old, target_id=tgt,
                                        reason="merged-404-contract",
                                        trigger="unit-test", evidence_cid=CID)
                await db.commit()
                return tgt, old, survivor

        tgt, old, survivor = self._run(go())
        self.assertEqual(survivor, tgt)

        async def read(cid_for_read):
            async with self._session() as db:
                return await get_chemical_detail(
                    db, cid_for_read, actor_id=None, priority=0, enrich="core")

        # ① 旧 HCID → 404（裁定本体）
        with self.assertRaises(ChemicalNotFoundError):
            self._run(read(old))
        # ② survivor 正常
        detail = self._run(read(tgt))
        self.assertEqual(detail["id"], tgt)

        async def check_redirect():
            async with self._session() as db:
                rows = (await db.execute(text(
                    "SELECT old_chemical_id, canonical_chemical_id FROM maintenance.chemical_identity_redirect "
                    "WHERE old_chemical_id=:o"), {"o": old})).all()
                canonical = await canonicalize_id(db, old)
                return rows, canonical

        # ③ redirect 在表、可解析（内部链路语义保留）
        rows, canonical = self._run(check_redirect())
        self.assertTrue(rows, "redirect 记录应存在（身份历史不删）")
        self.assertEqual(canonical, tgt)


if __name__ == "__main__":
    unittest.main()
