"""PubChem 回补链的 CID 回写（hermetic，需 test DB）。

worker/whole_record.py 的解析产物 core 不含 "CID" 键；若回调
(complete_pubchem_job) 只把 core.CID 当作 incoming CID evidence，主表
chemistry.chemicals.pubchem_cid 永远不回写，后续 enrichment 链断。因此
已验证的 query binding（job.query_value = worker 实际被派发请求的 CID）
作为可信 CID evidence —— core 缺 CID 时以 expected_cid 进。

锁四条：
1. core 无 CID + query_value=<cid> → 主表 pubchem_cid 回写（主线）；
2. core.CID == query_value → 照常回写（既有行为回归）；
3. 行上已有不同 CID → cid-conflict 硬闸：pubchem_cid 保持原值、事实零写入
   （「不同可信 CID 不得合并」不放松）；
4. 他行已持有该 CID → same-CID 收敛（absorb）落 survivor，survivor 身份
   不变（收敛路径）。

运行: TEST_DATABASE_URL="postgresql+asyncpg://…/test_hgs?test_sentinel=hgs-test-db" \
      python -m unittest tests.test_pubchem_cid_grant
（与 test_admin_worker_delete 同一 hermetic 模式；无 test DB 时整类跳过）
"""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("HGS_DATABASE_URL", os.environ.get("TEST_DATABASE_URL", ""))

try:
    from tests.db_gate import test_db_or_skip  # noqa: E402

    _RAW = test_db_or_skip()
    DB_URL = "postgresql+asyncpg://" + _RAW.split("://", 1)[1].split("?", 1)[0]
except Exception:  # pragma: no cover - 无 test DB 时跳过 DB 用例
    DB_URL = None

RUN = os.urandom(4).hex()
WORKER = f"wk-fnew01-{RUN}"
CID = 2244  # 阿司匹林（与生产数据无关 —— test 库隔离）


def _make_payload(cid: int | None = None, ik: str | None = None) -> dict:
    """whole_record 现状形状：core 有 Title/SMILES(/InChIKey)，无 CID。"""
    core: dict = {"Title": "Aspirin", "SMILES": "CC(=O)Oc1ccccc1C(=O)O"}
    if cid is not None:
        core["CID"] = cid
    if ik is not None:
        core["InChIKey"] = ik
    return {
        "core": core,
        "record_title": "Aspirin",
        "record_description": "acetylsalicylic acid",
        "computed": {},
        "physical": {"Boiling Point": ["140 °C"]},
    }


@unittest.skipIf(DB_URL is None, "no test DB")
class PubchemCidGrantTests(unittest.IsolatedAsyncioTestCase):
    """complete_pubchem_job 的 query-binding CID 回写。"""

    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        self.engine = create_async_engine(DB_URL)
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        self.made_chemicals: list[int] = []
        self.made_jobs: list[int] = []
        await self._make_worker()

    async def asyncTearDown(self):
        from sqlalchemy import text

        async with self.Session() as db:
            # hermetic 清理：本测试造的 job/receipt/worker + 化合物行。
            # 化合物行可能经 absorb 收敛到 survivor（redirect 落表）——
            # 顺 maintenance.chemical_identity_redirect 把 survivor 一并收回
            # （本类所有行均为自建，不触碰共享种子数据）。
            redirect_rows = (await db.execute(text("""
                SELECT old_chemical_id, canonical_chemical_id
                FROM maintenance.chemical_identity_redirect
                WHERE old_chemical_id = ANY(:ids)
            """), {"ids": self.made_chemicals})).fetchall()
            ids = set(self.made_chemicals)
            for r in redirect_rows:
                ids.add(int(r[0]))
                ids.add(int(r[1]))
            await db.execute(text("""
                DELETE FROM maintenance.workapi_completion_receipts
                WHERE worker_id=:w AND completed_at > now() - interval '1 hour'
            """), {"w": WORKER})
            await db.execute(text(
                "DELETE FROM maintenance.pubchem_jobs WHERE lease_owner=:w"
            ), {"w": WORKER})
            await db.execute(text(
                "DELETE FROM maintenance.worker_clients WHERE worker_id=:w"
            ), {"w": WORKER})
            if ids:
                await db.execute(text(
                    "DELETE FROM chemistry.chemical_pubchem WHERE chemical_id = ANY(:ids)"
                ), {"ids": sorted(ids)})
                await db.execute(text("""
                    DELETE FROM maintenance.chemical_identity_redirect
                    WHERE old_chemical_id = ANY(:ids) OR canonical_chemical_id = ANY(:ids)
                """), {"ids": sorted(ids)})
                await db.execute(text(
                    "DELETE FROM chemistry.chemicals WHERE id = ANY(:ids)"
                ), {"ids": sorted(ids)})
            await db.commit()
        await self.engine.dispose()

    async def _make_worker(self) -> None:
        from sqlalchemy import text

        import hashlib
        digest = hashlib.sha256(WORKER.encode()).digest()
        async with self.Session() as db:
            await db.execute(text("""
                INSERT INTO maintenance.worker_clients
                (worker_id, display_name, token_hash, token_prefix, scopes, max_lease_jobs)
                VALUES (:wid, :name, :digest, :prefix, CAST(:scopes AS text[]), 4)
                ON CONFLICT (worker_id) DO NOTHING
            """), {"wid": WORKER, "name": "fnew01-test", "digest": digest,
                   "prefix": "beef" + RUN[:4], "scopes": ["pubchem"]})
            await db.commit()

    async def _make_chemical(self, cid=None, ik=None) -> int:
        from sqlalchemy import text

        async with self.Session() as db:
            row = (await db.execute(text("""
                INSERT INTO chemistry.chemicals
                  (smiles, pubchem_cid, inchikey, mol, morgan_bfp, morgan_sfp,
                   created_at, updated_at)
                VALUES ('CCC(=O)O', :cid, :ik, mol_from_smiles('CCC(=O)O'),
                        morganbv_fp(mol_from_smiles('CCC(=O)O')),
                        morgan_fp(mol_from_smiles('CCC(=O)O')), now(), now())
                RETURNING id
            """), {"cid": cid, "ik": ik})).scalar()
            await db.commit()
            self.made_chemicals.append(int(row))
            return int(row)

    async def _lease_job(self, chemical_id: int, query_value: str) -> tuple[int, str]:
        from sqlalchemy import text

        from api.services.workqueue import lease_hash

        # LeaseProof 契约：lease_token 32–256 字符
        token = f"tok-{RUN}-{len(self.made_jobs) + 1}-" + "x" * 32
        async with self.Session() as db:
            jid = (await db.execute(text("""
                INSERT INTO maintenance.pubchem_jobs
                  (chemical_id, query_value, status, dedupe_key,
                   lease_owner, lease_token_hash, lease_expires_at)
                VALUES (:cid, :qv, 'leased', :dk, :wid, :th,
                        now() + interval '10 minutes')
                RETURNING id
            """), {
                "cid": chemical_id, "qv": query_value,
                "dk": f"dk-{RUN}-{token}", "wid": WORKER,
                "th": lease_hash(token),
            })).scalar()
            await db.commit()
            self.made_jobs.append(int(jid))
            return int(jid), token

    async def _complete(self, job_id: int, token: str, result: dict) -> dict:
        from api.services.workapi_jobs import complete_pubchem_job

        async with self.Session() as db:
            return await complete_pubchem_job(
                db, job_id=job_id, worker_id=WORKER,
                lease_token=token, result=result)

    async def _cid_of(self, chemical_id: int):
        from sqlalchemy import text

        async with self.Session() as db:
            row = (await db.execute(text(
                "SELECT pubchem_cid FROM chemistry.chemicals WHERE id=:id"
            ), {"id": chemical_id})).first()
            return row[0] if row else None

    async def _details_exist(self, chemical_id: int) -> bool:
        from sqlalchemy import text

        async with self.Session() as db:
            n = (await db.execute(text(
                "SELECT count(*) FROM chemistry.chemical_pubchem WHERE chemical_id=:id"
            ), {"id": chemical_id})).scalar()
            return int(n) > 0

    async def test_1_query_binding_grants_cid_without_core_cid(self):
        """主线：core 无 CID，query_value 回写主表。"""
        chem = await self._make_chemical()
        jid, token = await self._lease_job(chem, str(CID))
        out = await self._complete(jid, token, {"payload": _make_payload()})
        self.assertEqual(out["status"], "ok")
        self.assertEqual(await self._cid_of(chem), CID,
                         "query_value 未回写主表 pubchem_cid")
        self.assertTrue(await self._details_exist(chem), "详情零写入")

    async def test_2_core_cid_matching_query_still_grants(self):
        """core.CID 与 query_value 一致 → 照常回写（既有行为）。"""
        chem = await self._make_chemical()
        jid, token = await self._lease_job(chem, str(CID))
        out = await self._complete(jid, token, {"payload": _make_payload(cid=CID)})
        self.assertEqual(out["status"], "ok")
        self.assertEqual(await self._cid_of(chem), CID)

    async def test_3_existing_different_cid_hard_gate(self):
        """行上已有不同 CID → 硬闸：身份保持原值、事实零写入。"""
        chem = await self._make_chemical(cid=1111)
        jid, token = await self._lease_job(chem, str(CID))
        out = await self._complete(jid, token, {"payload": _make_payload()})
        self.assertEqual(out["status"], "ok")
        self.assertEqual(await self._cid_of(chem), 1111,
                         "不同可信 CID 被合并/覆盖 —— 硬闸失效")
        self.assertFalse(await self._details_exist(chem),
                         "conflict 分支必须事实零写入")

    async def test_4_same_cid_converges_to_survivor(self):
        """他行已持有该 CID → same-CID 收敛（absorb）落 survivor。"""
        survivor = await self._make_chemical(cid=CID)
        fork = await self._make_chemical()
        jid, token = await self._lease_job(fork, str(CID))
        out = await self._complete(jid, token, {"payload": _make_payload()})
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out.get("chemical_id"), survivor,
                         f"same-CID fork 未收敛到 survivor（期望 {survivor}，"
                         f"返回 {out.get('chemical_id')}）")
        self.assertEqual(await self._cid_of(survivor), CID)


if __name__ == "__main__":
    unittest.main()
