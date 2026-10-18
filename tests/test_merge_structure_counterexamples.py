"""合并/结构/收包语义的反例集（真实 PG 反例，hermetic）。

每项先写反例（按修复口径断言），红=问题成立；随后按语义修复翻绿。
撤销项不出现在本文件。

覆盖:
- 合并 absorb 主表核心字段漏迁（survivor 空时不补；双侧非空冲突时无留痕）。
- reaction_chemicals 同键计量冲突无留痕；
  chemical_pubchem.identifier_evidence survivor '{}' 不吸收对方非空证据。
- 同一可信 CID、IK 有差异 → 整包事实被扣留却记 ok；
  真实冲突扣留时回执必须如实（不得记 ok）。
- 供应商表全删全写丢他源；SMILES/IK/MOL 互不交叉校验；
  只有 SMILES 时不推导 IK；CAS 回调双 miss 建幽灵行。
- ≥2 行同 IK 且同挂另一个 CID 时漏报 CONFLICT；CAS 单候选不核对强键互斥。
- ≥3 行同 CID 只收敛第一个；合并后活动任务 dedupe_key 前缀失配。

运行: TEST_DATABASE_URL="postgresql+asyncpg://…/test_hgs?test_sentinel=hgs-test-db" \
      python -m unittest tests.test_merge_structure_counterexamples
"""
from __future__ import annotations

import hashlib
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
WORKER = f"wk-cx-{RUN}"
TRIGGER = "cx-unit-test"

# 测试标记值 —— 与既有套件(test_identity/test_pubchem_cid_grant)隔离
CID = 990001234          # A1/A3 主标记
CID_CONFLICT = 990001111  # A3 冲突标记
CID_A2 = 990001222        # A2
CID_A4 = 990001333        # A4
CID_A5 = 990001444        # A5
CID_A6 = 990001555        # A6
CAS = "99998-77-7"
IK_ETHANOL = "LFQSCWFLJHTTHZ-UHFFFAOYSA-N"   # RDKit MolToInchiKey('CCO')
IK_OTHER = "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"     # 阿司匹林 —— 与乙醇必然不同
IK_METHANOL = "OKKJLVBELUTLKV-UHFFFAOYSA-N"  # RDKit MolToInchiKey('CO')
IKS = (IK_ETHANOL, IK_OTHER, IK_METHANOL)


def _rxn(cas: str) -> str:
    return f"cas:{cas}"


@unittest.skipIf(DB_URL is None, "no test DB")
class CounterexampleBase(unittest.IsolatedAsyncioTestCase):
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
            # 化合物行可能经 absorb 收敛 —— 顺 redirect 把 survivor 一并回收;
            # 再扫一遍标记行(幽灵行路径由 resolver INSERT, 不在 made_chemicals)
            redirect_rows = (await db.execute(text("""
                SELECT old_chemical_id, canonical_chemical_id
                FROM maintenance.chemical_identity_redirect
                WHERE old_chemical_id = ANY(:ids)
            """), {"ids": self.made_chemicals})).fetchall()
            ids = set(self.made_chemicals)
            for r in redirect_rows:
                ids.add(int(r[0]))
                ids.add(int(r[1]))
            marker_rows = (await db.execute(text("""
                SELECT id FROM chemistry.chemicals
                WHERE inchikey IN (:ik1, :ik2)
                   OR cas_numbers @> ARRAY[:cas]
                   OR dtxsid LIKE 'DTX%CX'
                   OR pubchem_cid IN (:c1, :c2, :c3, :c4, :c5, :c6, :c7, :c8)
            """), {"ik1": IK_ETHANOL, "ik2": IK_OTHER, "cas": CAS,
                   "c1": CID, "c2": CID_CONFLICT, "c3": CID_A2, "c4": CID_A2 + 1,
                   "c5": CID_A4, "c6": CID_A5, "c7": CID_A5 + 3,
                   "c8": CID_A6 + 2})).scalars().all()
            ids.update(int(i) for i in marker_rows)
            ids.discard(None)
            # 引用表清理(本类自建行 + 幽灵行)
            if ids:
                await db.execute(text("""
                    DELETE FROM chemistry.reaction_chemicals WHERE chemical_id = ANY(:ids)
                """), {"ids": sorted(ids)})
                await db.execute(text("""
                    DELETE FROM chemistry.chemical_pubchem WHERE chemical_id = ANY(:ids)
                """), {"ids": sorted(ids)})
                await db.execute(text("""
                    DELETE FROM chemistry.chemical_cb WHERE chemical_id = ANY(:ids)
                """), {"ids": sorted(ids)})
                await db.execute(text("""
                    DELETE FROM chemistry.chemical_supplier_listing
                    WHERE chemical_id = ANY(:ids)
                """), {"ids": sorted(ids)})
                await db.execute(text("""
                    DELETE FROM chemistry.name_index WHERE chemical_id = ANY(:ids)
                """), {"ids": sorted(ids)})
                await db.execute(text("""
                    DELETE FROM maintenance.pubchem_identity_jobs
                    WHERE chemical_id = ANY(:ids)
                """), {"ids": sorted(ids)})
                await db.execute(text("""
                    DELETE FROM maintenance.chemical_identity_redirect
                    WHERE old_chemical_id = ANY(:ids)
                       OR canonical_chemical_id = ANY(:ids)
                """), {"ids": sorted(ids)})
                await db.execute(text("""
                    DELETE FROM maintenance.identity_merge_log
                    WHERE trigger = :tr
                      AND (source_id = ANY(:ids) OR target_id = ANY(:ids))
                """), {"tr": TRIGGER, "ids": sorted(ids)})
                await db.execute(text(
                    "DELETE FROM chemistry.chemicals WHERE id = ANY(:ids)"
                ), {"ids": sorted(ids)})
            await db.execute(text("""
                DELETE FROM maintenance.cas_jobs
                WHERE lease_owner = :w OR cas_number = :c OR dedupe_key LIKE :p
            """), {"w": WORKER, "c": CAS, "p": f"cx-{RUN}-%"})
            await db.execute(text("""
                DELETE FROM maintenance.pubchem_jobs
                WHERE lease_owner = :w OR query_value = :q OR dedupe_key LIKE :p
            """), {"w": WORKER, "q": str(CID_A6), "p": f"cx-{RUN}-%"})
            await db.execute(text("""
                DELETE FROM maintenance.workapi_completion_receipts
                WHERE worker_id = :w
            """), {"w": WORKER})
            await db.execute(text("""
                DELETE FROM maintenance.worker_clients WHERE worker_id = :w
            """), {"w": WORKER})
            await db.execute(text(
                "DELETE FROM chemistry.chemical_supplier_profile"
                " WHERE cbsid LIKE 'CXSUP%'"
            ))
            await db.commit()
        await self.engine.dispose()

    async def _make_worker(self) -> None:
        from sqlalchemy import text

        digest = hashlib.sha256(WORKER.encode()).digest()
        async with self.Session() as db:
            await db.execute(text("""
                INSERT INTO maintenance.worker_clients
                (worker_id, display_name, token_hash, token_prefix, scopes, max_lease_jobs)
                VALUES (:wid, :name, :digest, :prefix, CAST(:scopes AS text[]), 4)
                ON CONFLICT (worker_id) DO NOTHING
            """), {"wid": WORKER, "name": "cx-test", "digest": digest,
                   "prefix": "c0de" + RUN[:4],
                   "scopes": ["pubchem", "cas"]})
            await db.commit()

    async def _chemical(self, *, cid=None, ik=None, cas=None, mol_smiles=None,
                        core: dict | None = None, cb=None,
                        fingerprints: bool = False) -> int:
        """插入测试化合物行；core 直接覆盖主表列。"""
        from sqlalchemy import text

        cols = ["created_at", "updated_at"]
        vals = ["now()", "now()"]
        params: dict = {}

        def add(col: str, val_sql: str, param=None) -> None:
            cols.append(col)
            vals.append(val_sql)
            if param is not None:
                params[col] = param

        if cid is not None:
            add("pubchem_cid", ":pubchem_cid", cid)
        if ik is not None:
            add("inchikey", ":inchikey", ik)
        if cb is not None:
            add("cb_number", ":cb_number", cb)
        if cas:
            add("cas_numbers", ":cas_numbers", [cas])
        if mol_smiles:
            add("smiles", ":smiles", mol_smiles)
            add("mol", f"mol_from_smiles('{mol_smiles}')")
            if fingerprints:
                add("morgan_bfp", f"morganbv_fp(mol_from_smiles('{mol_smiles}'))")
                add("morgan_sfp", f"morgan_fp(mol_from_smiles('{mol_smiles}'))")
        for k, v in (core or {}).items():
            add(k, "CAST(:%s AS jsonb)" % k if k == "synonyms" else f":{k}", v)
        sql = (f"INSERT INTO chemistry.chemicals ({','.join(cols)})"
               f" VALUES ({','.join(vals)}) RETURNING id")
        async with self.Session() as db:
            row = (await db.execute(text(sql), params)).scalar()
            await db.commit()
        self.made_chemicals.append(int(row))
        return int(row)

    async def _row(self, chemical_id: int) -> dict:
        from sqlalchemy import text

        async with self.Session() as db:
            r = (await db.execute(text(
                "SELECT to_jsonb(c) FROM chemistry.chemicals c WHERE c.id=:id"
            ), {"id": chemical_id})).scalar()
        return dict(r) if r else {}

    async def _merge_log(self, survivor_id: int) -> dict:
        from sqlalchemy import text

        async with self.Session() as db:
            r = (await db.execute(text("""
                SELECT evidence FROM maintenance.identity_merge_log
                WHERE target_id = :t AND trigger = :tr
                ORDER BY merge_id DESC LIMIT 1
            """), {"t": survivor_id, "tr": TRIGGER})).scalar()
        import json
        return r if isinstance(r, dict) else (json.loads(r) if r else {})


# ── 合并: absorb 主表核心字段 ────────────────────────────────────────────

class A1MergeCoreTests(CounterexampleBase):
    async def test_core_fields_fill_empty(self):
        """survivor 核心字段为空 → 被吸收方补入（当前: 直接随行删除 → 红）。"""
        from api.services.identity import absorb
        import json
        survivor = await self._chemical(cid=CID, mol_smiles="CCO")
        dtxsid = f"DTX{RUN.upper()}CX"
        await self._chemical(
            cid=CID, mol_smiles="CCO", fingerprints=True,
            core={
                "pubchem_smiles": "CCO",
                "iupac_name": "ethanol",
                "molecular_formula": "C2H6O",
                "average_mass": 46.07,
                "monoisotopic_mass": 46.0419,
                "dtxsid": dtxsid,
                "nikkaji_numbers": ["N1-CX"],
                "chembl_ids": ["CHEMBL-CX"],
                "synonyms": json.dumps(["ethyl alcohol"]),
            })
        async with self.Session() as db:
            surv = await absorb(db, source_id=self.made_chemicals[-1],
                                target_id=survivor, reason="cx-a1",
                                trigger=TRIGGER)
            await db.commit()
        row = await self._row(surv)
        self.assertEqual(row["pubchem_smiles"], "CCO", "pubchem_smiles 漏迁")
        self.assertEqual(row["iupac_name"], "ethanol", "iupac_name 漏迁")
        self.assertEqual(row["molecular_formula"], "C2H6O", "molecular_formula 漏迁")
        self.assertEqual(float(row["average_mass"]), 46.07, "average_mass 漏迁")
        self.assertEqual(float(row["monoisotopic_mass"]), 46.0419,
                         "monoisotopic_mass 漏迁")
        self.assertEqual(row["dtxsid"], dtxsid, "命名 ID (dtxsid) 漏迁")
        self.assertIn("N1-CX", row["nikkaji_numbers"] or [],
                      "命名 ID (nikkaji) 漏迁")
        self.assertIn("CHEMBL-CX", row["chembl_ids"] or [],
                      "命名 ID (chembl) 漏迁")
        self.assertIsNotNone(row["mol"], "mol 漏迁")
        self.assertIsNotNone(row["morgan_bfp"], "分子指纹漏迁")

    async def test_conflict_keeps_survivor_and_traces(self):
        """双侧非空且冲突 → survivor 保留 + merge_log 留痕（当前: 无痕 → 红）。"""
        import json
        from api.services.identity import absorb
        survivor = await self._chemical(
            cid=CID + 1, mol_smiles="CCO",
            core={"iupac_name": "survivor-name",
                  "molecular_formula": "C2H6O"})
        await self._chemical(
            cid=CID + 1, mol_smiles="CCO",
            core={"iupac_name": "absorbed-name",
                  "molecular_formula": "C2H5O"})
        async with self.Session() as db:
            surv = await absorb(db, source_id=self.made_chemicals[-1],
                                target_id=survivor, reason="cx-a1b",
                                trigger=TRIGGER)
            await db.commit()
        row = await self._row(surv)
        self.assertEqual(row["iupac_name"], "survivor-name", "冲突时 survivor 值被覆盖")
        self.assertEqual(row["molecular_formula"], "C2H6O")
        log = await self._merge_log(surv)
        conflicts = log.get("core_conflicts") or {}
        self.assertIn("iupac_name", conflicts,
                      "iupac_name 冲突未在 merge_log 留痕")
        self.assertIn("molecular_formula", conflicts,
                      "molecular_formula 冲突未在 merge_log 留痕")
        c = conflicts["iupac_name"]
        if isinstance(c, str):
            c = json.loads(c)
        self.assertEqual(c.get("survivor"), "survivor-name")
        self.assertEqual(c.get("absorbed"), "absorbed-name")


# ── A2 / ──────────────────────────────────────────

class A2MergePayloadTests(CounterexampleBase):
    async def test_reaction_metering_conflict_traced(self):
        """同 reaction+role 计量冲突 → survivor 保留 + 留痕（当前: 静默丢 → 红）。"""
        from sqlalchemy import text
        from api.services.identity import absorb
        survivor = await self._chemical(cid=CID_A2, mol_smiles="CCO")
        await self._chemical(cid=CID_A2)
        async with self.Session() as db:
            await db.execute(text(
                "INSERT INTO chemistry.reactions (id) VALUES (987001)"
                " ON CONFLICT DO NOTHING"))
            await db.execute(text("""
                INSERT INTO chemistry.reaction_chemicals
                  (reaction_id, chemical_id, role, occurrence_count, amount_value)
                VALUES (987001,:c,'REACTANT',1,1.0)
            """), {"c": survivor})
            await db.execute(text("""
                INSERT INTO chemistry.reaction_chemicals
                  (reaction_id, chemical_id, role, occurrence_count, amount_value)
                VALUES (987001,:c,'REACTANT',3,7.5)
            """), {"c": self.made_chemicals[-1]})
            await db.commit()
            surv = await absorb(db, source_id=self.made_chemicals[-1],
                                target_id=survivor, reason="cx-a2",
                                trigger=TRIGGER)
            await db.commit()
            kept = (await db.execute(text("""
                SELECT occurrence_count, amount_value
                FROM chemistry.reaction_chemicals
                WHERE reaction_id=987001 AND chemical_id=:c AND role='REACTANT'
            """), {"c": surv})).first()
        self.assertEqual(tuple(kept), (1, 1.0), "冲突时 survivor 值必须保留")
        log = await self._merge_log(surv)
        payload_conflicts = log.get("payload_conflicts") or {}
        rxn = payload_conflicts.get("chemistry.reaction_chemicals") or []
        self.assertTrue(rxn, "同 reaction+role 计量冲突未在 merge_log 留痕")
        for col, sv, ab in (("occurrence_count", 1, 3), ("amount_value", 1.0, 7.5)):
            hit = [x for x in rxn if x.get("column") == col]
            self.assertTrue(hit, f"{col} 冲突未留痕")
            self.assertEqual(hit[0].get("survivor"), sv)
            self.assertEqual(hit[0].get("absorbed"), ab)

    async def test_pb_evidence_empty_object_absorbs(self):
        """survivor PB 证据 '{}' → 吸收对方非空证据（当前: 不吸收 → 红）。"""
        from sqlalchemy import text
        from api.services.identity import absorb
        survivor = await self._chemical(cid=CID_A2 + 1, mol_smiles="CCO")
        await self._chemical(cid=CID_A2 + 1)
        async with self.Session() as db:
            await db.execute(text("""
                INSERT INTO chemistry.chemical_pubchem
                  (chemical_id, identifier_evidence, ghs_classification)
                VALUES (:c, '{}'::jsonb, '{}'::jsonb)
            """), {"c": survivor})
            await db.execute(text("""
                INSERT INTO chemistry.chemical_pubchem
                  (chemical_id, identifier_evidence, ghs_classification)
                VALUES (:c, CAST(:evid AS jsonb), CAST(:ghs AS jsonb))
            """), {"c": self.made_chemicals[-1],
                   "evid": '{"CAS": ["99998-77-7"]}',
                   "ghs": '{"h226": ["flammable"]}'})
            await db.commit()
            surv = await absorb(db, source_id=self.made_chemicals[-1],
                                target_id=survivor, reason="cx-a2b",
                                trigger=TRIGGER)
            await db.commit()
            r = (await db.execute(text("""
                SELECT identifier_evidence::text, ghs_classification::text,
                       count(*) OVER () AS n
                FROM chemistry.chemical_pubchem WHERE chemical_id=:c
            """), {"c": surv})).first()
        import json
        self.assertEqual(r[2], 1, "旧 1:1 行未删")
        self.assertEqual(json.loads(r[0]), {"CAS": ["99998-77-7"]},
                         "survivor '{}' 未吸收对方非空 identifier_evidence")
        self.assertEqual(json.loads(r[1]), {"h226": ["flammable"]},
                         "survivor '{}' 未吸收对方非空 ghs_classification")


# ── A3 F-NEW-02 / ─────────────────────────────────────────────────

class A3PubchemIkDivergenceTests(CounterexampleBase):
    def _payload(self, cid: int, ik: str) -> dict:
        return {"payload": {
            "core": {
                "CID": cid, "InChIKey": ik, "Title": "Ethanol",
                "IUPACName": "ethanol-different-ik",
                "SMILES": "CCO", "MolecularFormula": "C2H6O",
                "MolecularWeight": 46.07,
            },
            "record_title": "Ethanol",
            "computed": {}, "physical": {"Boiling Point": ["78 °C"]},
        }}

    async def _lease(self, chemical_id: int, query_value: str) -> tuple[int, str]:
        from sqlalchemy import text
        from api.services.workqueue import lease_hash

        token = f"tok-{RUN}-{len(self.made_jobs) + 1}-" + "x" * 32
        async with self.Session() as db:
            jid = (await db.execute(text("""
                INSERT INTO maintenance.pubchem_jobs
                  (chemical_id, query_value, status, dedupe_key,
                   lease_owner, lease_token_hash, lease_expires_at)
                VALUES (:cid, :qv, 'leased', :dk, :wid, :th,
                        now() + interval '10 minutes')
                RETURNING id
            """), {"cid": chemical_id, "qv": query_value,
                   "dk": f"cx-{RUN}-{token[:16]}", "wid": WORKER,
                   "th": lease_hash(token)})).scalar()
            await db.commit()
        self.made_jobs.append(int(jid))
        return int(jid), token

    async def _complete(self, job_id: int, token: str, result: dict) -> dict:
        from api.services.workapi_jobs import complete_pubchem_job
        async with self.Session() as db:
            return await complete_pubchem_job(
                db, job_id=job_id, worker_id=WORKER,
                lease_token=token, result=result)

    async def _receipt_status(self, job_id: int) -> str | None:
        from sqlalchemy import text
        async with self.Session() as db:
            r = (await db.execute(text("""
                SELECT terminal_status FROM maintenance.workapi_completion_receipts
                WHERE family='pubchem' AND job_id=:j
            """), {"j": job_id})).scalar()
        return r

    async def test_same_cid_ik_divergence_facts_land(self):
        """同一可信 CID + IK 差异 → 事实落库、行 IK 保留、回执 ok。

        CID 是唯一身份锚(撤销裁决）：IK 差异记录溯源，不扣留整包。"""
        chem = await self._chemical(cid=CID, ik=IK_OTHER, mol_smiles="CCO")
        jid, token = await self._lease(chem, str(CID))
        out = await self._complete(jid, token, self._payload(CID, IK_ETHANOL))
        self.assertEqual(out["status"], "ok")
        row = await self._row(chem)
        self.assertIsNotNone(row.get("iupac_name") or None,
                             "同 CID + IK 差异: 整包事实被扣留(F-NEW-02)")
        self.assertEqual(row["iupac_name"], "ethanol-different-ik",
                         "core 字段未落库")
        self.assertEqual(row["inchikey"], IK_OTHER,
                         "行上 IK 被 incoming 覆盖(应 existing-first 保留)")
        from sqlalchemy import text
        async with self.Session() as db:
            n = (await db.execute(text("""
                SELECT count(*) FROM chemistry.chemical_pubchem
                WHERE chemical_id=:c
            """), {"c": chem})).scalar()
        self.assertEqual(int(n), 1, "详情子表被扣留(F-NEW-02)")
        self.assertEqual(await self._receipt_status(jid), "ok",
                         "事实已落库, 回执不应记 withheld")

    async def test_genuine_conflict_receipt_is_honest(self):
        """真实 cid-conflict → 事实扣留, 但回执必须如实(不得记 ok)。"""
        chem = await self._chemical(cid=CID_CONFLICT, mol_smiles="CCO")
        jid, token = await self._lease(chem, str(CID))
        out = await self._complete(jid, token, self._payload(CID, IK_ETHANOL))
        self.assertEqual(out["status"], "ok")  # 协议层 ack 不变
        status = await self._receipt_status(jid)
        self.assertNotEqual(status, "ok",
                            "扣留了整包事实却把任务记成 ok(收包语义)")
        self.assertIn("withheld", (status or ""),
                      "回执应记 withheld 类终态, 实际: %r" % status)


# ── CB 源与结构交叉校验 ───────────────────────────────────

class A4CbSourceTests(CounterexampleBase):
    async def test_suppliers_multi_source_merge(self):
        """两个 CB source 依次回调 → 供应商行并存, 不互相覆盖。"""
        from api.services.cb import upsert_externals
        chem = await self._chemical(cid=CID_A4, cas=CAS)
        base_entry = {"identity": {"cn": "乙醇", "en": "Ethanol",
                                   "formula": "C2H6O", "mw": 46.07}}
        async with self.Session() as db:
            await upsert_externals(
                db, chemical_id=chem, cas_number=CAS, entry=base_entry,
                suppliers=[{"cbsid": "CXSUP1", "name": "Supplier One",
                            "purity": "99%"}],
                status="ok", cb_number="99000001", locale="zh-CN")
            await upsert_externals(
                db, chemical_id=chem, cas_number=CAS, entry=base_entry,
                suppliers=[{"cbsid": "CXSUP2", "name": "Supplier Two",
                            "purity": "98%"}],
                status="ok", cb_number="99000002", locale="zh-CN")
            await db.commit()
            from sqlalchemy import text
            rows = (await db.execute(text("""
                SELECT cbsid FROM chemistry.chemical_supplier_listing
                WHERE chemical_id=:c ORDER BY cbsid
            """), {"c": chem})).scalars().all()
        self.assertEqual(rows, ["CXSUP1", "CXSUP2"],
                         "后到的 CB source 覆盖了先到 source 的供应商行(多源并存语义)")

    async def test_structure_cross_validation(self):
        """SMILES/IK/MOL 交叉校验: 不一致 → 拒写。"""
        from api.services.cb import resolve_structure
        entry_bad = {"props": [
            {"key": "smiles", "text": "CCO"},
            {"key": "inchikey", "text": IK_OTHER},  # 乙醇 SMILES 配阿司匹林 IK
        ]}
        out = resolve_structure(entry_bad, None)
        self.assertIsNone(out["smiles"],
                          "SMILES/IK 语义不一致仍写 smiles(交叉校验)")
        self.assertIsNone(out["inchikey"],
                          "SMILES/IK 语义不一致仍写 inchikey(交叉校验)")
        # 一致数据照常通过(回归)
        entry_ok = {"props": [
            {"key": "smiles", "text": "CCO"},
            {"key": "inchikey", "text": IK_ETHANOL},
        ]}
        out = resolve_structure(entry_ok, None)
        self.assertEqual(out["smiles"], "CCO")
        self.assertEqual(out["inchikey"], IK_ETHANOL)

    async def test_smiles_only_derives_ik(self):
        """只有 SMILES → RDKit 推导 IK → 进入发现流程。"""
        from api.services.cb import apply_structure_fill, resolve_structure
        entry = {"props": [{"key": "smiles", "text": "CCO"}]}
        out = resolve_structure(entry, None)
        self.assertEqual(out["inchikey"], IK_ETHANOL,
                         "只有 SMILES 时未推导 IK(结构推导)")
        chem = await self._chemical(cid=None)
        async with self.Session() as db:
            await apply_structure_fill(db, chem, out)
            await db.commit()
        row = await self._row(chem)
        self.assertEqual(row["inchikey"], IK_ETHANOL, "推导 IK 未回填主表")
        from sqlalchemy import text
        async with self.Session() as db:
            n = (await db.execute(text("""
                SELECT count(*) FROM maintenance.pubchem_identity_jobs
                WHERE chemical_id=:c AND status='queued'
            """), {"c": chem})).scalar()
        self.assertEqual(int(n), 1, "SMILES 推导 IK 后未进入 discovery 发现流程")

    async def test_cas_complete_no_ghost_row(self):
        """CAS 回调双 miss 时不得建幽灵行(complete 解析必须 create=False)。"""
        from api.schemas.workapi import CasResultBody
        from api.services.workapi_jobs import complete_cas_job
        from sqlalchemy import text
        from api.services.workqueue import lease_hash

        chem = await self._chemical()  # 无 CAS、无 IK、无 CID
        token = f"tok-{RUN}-ghost-" + "x" * 32
        entry = {"props": [{"key": "smiles", "text": "CCO"},
                           {"key": "inchikey", "text": IK_ETHANOL}]}
        async with self.Session() as db:
            jid = (await db.execute(text("""
                INSERT INTO maintenance.cas_jobs
                  (chemical_id, cas_number, status, dedupe_key,
                   lease_owner, lease_token_hash, lease_expires_at)
                VALUES (:cid, :cas, 'leased', :dk, :wid, :th,
                        now() + interval '10 minutes')
                RETURNING id
            """), {"cid": chem, "cas": CAS, "dk": f"cx-{RUN}-ghost",
                   "wid": WORKER, "th": lease_hash(token)})).scalar()
            await db.commit()
        self.made_jobs.append(int(jid))
        payload = CasResultBody(status="ok", entry=entry, suppliers=[],
                                cb_number="99000003", locale="zh-CN")
        async with self.Session() as db:
            await complete_cas_job(db, job_id=int(jid), worker_id=WORKER,
                                   lease_token=token, result=payload)
        async with self.Session() as db:
            n = (await db.execute(text(
                "SELECT count(*) FROM chemistry.chemicals WHERE inchikey=:ik"
            ), {"ik": IK_ETHANOL})).scalar()
        self.assertEqual(int(n), 1,
                         "CAS 回调双 miss 建出幽灵行(占位行约束), 实际行数: %d" % n)


# ── CB 回调结构写入(CONFLICT + IK 相异才拒写) ────────────────────────────

class CbCallbackStructureConflictTests(CounterexampleBase):
    """resolver CONFLICT 且载荷 IK ≠ 行已有 IK → 跳过 apply_structure_fill
    (只补空也会把 smiles/mol/指纹写成异物); 其余路径(无 CID 但结构一致的
    正常补全)照旧填 IK。"""

    async def _leased_job(self, chemical_id: int, tag: str) -> tuple[int, str]:
        from sqlalchemy import text
        from api.services.workqueue import lease_hash

        token = f"tok-{RUN}-zx-{tag}-" + "x" * 32
        async with self.Session() as db:
            jid = (await db.execute(text("""
                INSERT INTO maintenance.cas_jobs
                  (chemical_id, cas_number, status, dedupe_key,
                   lease_owner, lease_token_hash, lease_expires_at)
                VALUES (:cid, :cas, 'leased', :dk, :wid, :th,
                        now() + interval '10 minutes')
                RETURNING id
            """), {"cid": chemical_id, "cas": CAS,
                   "dk": f"cx-{RUN}-zx-{tag}",
                   "wid": WORKER, "th": lease_hash(token)})).scalar()
            await db.commit()
        self.made_jobs.append(int(jid))
        return int(jid), token

    async def _complete(self, job_id: int, token: str, entry: dict) -> None:
        from api.schemas.workapi import CasResultBody
        from api.services.workapi_jobs import complete_cas_job

        payload = CasResultBody(status="ok", entry=entry, suppliers=[],
                                cb_number="99000009", locale="zh-CN")
        async with self.Session() as db:
            await complete_cas_job(db, job_id=job_id, worker_id=WORKER,
                                   lease_token=token, result=payload)

    async def _structure_state(self, chemical_id: int) -> dict:
        from sqlalchemy import text
        async with self.Session() as db:
            r = (await db.execute(text("""
                SELECT inchikey, smiles, (mol IS NOT NULL) AS has_mol,
                       (morgan_bfp IS NOT NULL) AS has_bfp, updated_at
                FROM chemistry.chemicals WHERE id=:id
            """), {"id": chemical_id})).mappings().first()
        return dict(r) if r else {}

    async def test_conflict_divergent_ik_zero_structure_change(self):
        """甲醇 IK 行遇乙醇载荷: resolver CONFLICT(cas-unique-ik-conflict),
        主表结构零变动(只补空也不写 smiles/mol/指纹)。"""
        chem = await self._chemical(ik=IK_METHANOL, cas=CAS, mol_smiles="CO",
                                    fingerprints=True)
        before = await self._structure_state(chem)
        jid, token = await self._leased_job(chem, "meoh")
        ethanol_entry = {"props": [
            {"key": "smiles", "text": "CCO"},
            {"key": "inchikey", "text": IK_ETHANOL},
        ]}
        await self._complete(jid, token, ethanol_entry)
        after = await self._structure_state(chem)
        for key in ("inchikey", "smiles", "has_mol", "has_bfp"):
            self.assertEqual(after[key], before[key],
                             f"CONFLICT+异 IK 载荷不得改动主表结构: {key}")
        self.assertEqual(after["inchikey"], IK_METHANOL)
        self.assertEqual(after["smiles"], "CO")

    async def test_no_cid_consistent_structure_still_fills_ik(self):
        """ 路径: 行无 CID、无 IK, 载荷结构一致(cas-unique-hit EQUIVALENT)
        — 照常补出 IK。"""
        chem = await self._chemical(cas=CAS)  # 无 ik、无 cid、无 mol
        jid, token = await self._leased_job(chem, "r01")
        entry = {"props": [
            {"key": "smiles", "text": "CCO"},
            {"key": "inchikey", "text": IK_ETHANOL},
        ]}
        await self._complete(jid, token, entry)
        after = await self._structure_state(chem)
        self.assertEqual(after["inchikey"], IK_ETHANOL,
                         "无 CID 但结构一致的正常补全必须照常回填 IK")


# ── A5 / ────────────────────────────────────────────────────────

class A5ResolverBranchTests(CounterexampleBase):
    async def _resolve(self, **kw):
        from api.services.identity import resolve_chemical
        async with self.Session() as db:
            return await resolve_chemical(db, **kw)

    async def test_multi_row_same_ik_same_other_cid_is_conflict(self):
        """≥2 行同 IK 且同挂另一个 CID → CONFLICT（当前: EQUIVALENT → 红）。"""
        await self._chemical(cid=CID_A5, ik=IK_ETHANOL, mol_smiles="CCO")
        await self._chemical(cid=CID_A5, ik=IK_ETHANOL, mol_smiles="CCO")
        res = await self._resolve(cid=CID_A5 + 1, inchikey=IK_ETHANOL)
        self.assertEqual(
            res.status, "CONFLICT",
            "库内 ≥2 行同 IK 且同挂 CID=%d、输入 CID=%d 应报 CONFLICT,"
            "实际 %s/%s" % (CID_A5, CID_A5 + 1, res.status, res.reason))

    async def test_cas_unique_checks_strong_key_mutex(self):
        """CAS 单候选命中必须核对强键互斥（cid / ik 两变体）。"""
        row_cid = await self._chemical(cid=CID_A5 + 2, cas=CAS)
        # 变体1: 输入 CID 与行 CID 相斥
        res = await self._resolve(cid=CID_A5 + 3, cas=CAS)
        self.assertEqual(
            res.status, "CONFLICT",
            "CAS 单候选行 CID=%d 与输入 CID=%d 相斥应报 CONFLICT,"
            "实际 %s/%s" % (CID_A5 + 2, CID_A5 + 3, res.status, res.reason))
        # 变体2: 输入 IK 与行 IK 相斥(行无 mol, IK 序位捞不到) —— 独立 CAS 隔离
        cas2 = "99998-77-8"
        await self._chemical(ik=IK_OTHER, cas=cas2)
        res = await self._resolve(inchikey=IK_ETHANOL, cas=cas2)
        self.assertEqual(
            res.status, "CONFLICT",
            "CAS 单候选行 IK=%s 与输入 IK=%s 相斥应报 CONFLICT,"
            "实际 %s/%s" % (IK_OTHER, IK_ETHANOL, res.status, res.reason))
        # 回归: 无强键 / 强键一致 → 仍命中该行
        res = await self._resolve(cas=CAS)
        self.assertEqual(res.chemical_id, row_cid, "无强键 CAS 单命中回归被破坏")
        res = await self._resolve(cid=CID_A5 + 2, cas=CAS)
        self.assertEqual(res.chemical_id, row_cid, "强键一致的 CAS 命中回归被破坏")
        res = await self._resolve(inchikey=IK_OTHER, cas=cas2)
        self.assertEqual(res.chemical_id, self.made_chemicals[-1],
                         "IK 一致的 CAS 命中回归被破坏")


# ── A6 / ─────────────────────────────────────────────

class A6ConvergenceTests(CounterexampleBase):
    async def test_three_way_same_cid_converges(self):
        """≥3 行同 CID → 全部收敛为 1 行（当前: 只收敛第一个 → 红）。"""
        from sqlalchemy import text
        from api.services.workqueue import reconcile_pubchem_identity
        a = await self._chemical(cid=CID_A6)
        await self._chemical(cid=CID_A6)
        await self._chemical(cid=CID_A6)
        async with self.Session() as db:
            canonical = await reconcile_pubchem_identity(db, a, CID_A6)
            await db.commit()
            n = (await db.execute(text("""
                SELECT count(*) FROM chemistry.chemicals WHERE pubchem_cid=:c
            """), {"c": CID_A6})).scalar()
        self.assertIn(canonical, self.made_chemicals)
        self.assertEqual(int(n), 1,
                         "≥3 行同 CID 收敛后仍残留 %d 行(同 CID 收敛)" % n)

    async def test_active_jobs_dedupe_key_rekeyed(self):
        """合并后活动任务 dedupe_key 前缀跟随 survivor（cas + pubchem）。"""
        from sqlalchemy import text
        from api.services.identity import absorb
        survivor = await self._chemical(cid=CID_A6 + 1, mol_smiles="CCO")
        absorbed = await self._chemical(cid=CID_A6 + 1)
        cas_digest = hashlib.sha256(CAS.strip().encode()).hexdigest()[:16]
        cid_digest = hashlib.sha256(str(CID_A6 + 1).encode()).hexdigest()[:16]
        async with self.Session() as db:
            await db.execute(text("""
                INSERT INTO maintenance.cas_jobs
                  (chemical_id, cas_number, status, dedupe_key, request_context)
                VALUES (:c, :cas, 'queued', :dk, '{}'::jsonb)
            """), {"c": absorbed, "cas": CAS,
                   "dk": f"cas:{absorbed}:{cas_digest}"})
            await db.execute(text("""
                INSERT INTO maintenance.pubchem_jobs
                  (chemical_id, query_value, status, dedupe_key, request_context)
                VALUES (:c, :qv, 'queued', :dk, '{}'::jsonb)
            """), {"c": absorbed, "qv": str(CID_A6 + 1),
                   "dk": f"cid:{absorbed}:{cid_digest}"})
            await db.commit()
            surv = await absorb(db, source_id=absorbed, target_id=survivor,
                                reason="cx-a6", trigger=TRIGGER)
            await db.commit()
            cas_job = (await db.execute(text("""
                SELECT chemical_id, dedupe_key FROM maintenance.cas_jobs
                WHERE cas_number=:cas
            """), {"cas": CAS})).first()
            pb_job = (await db.execute(text("""
                SELECT chemical_id, dedupe_key FROM maintenance.pubchem_jobs
                WHERE query_value=:qv
            """), {"qv": str(CID_A6 + 1)})).first()
        self.assertIsNotNone(cas_job, "cas job 被误删(无冲突不应删)")
        self.assertEqual(cas_job[0], surv, "cas job chemical_id 未改指")
        self.assertEqual(cas_job[1], f"cas:{surv}:{cas_digest}",
                         "cas job dedupe_key 前缀未跟随 survivor(合并后任务迁移)")
        self.assertIsNotNone(pb_job, "pubchem job 被误删(无冲突不应删)")
        self.assertEqual(pb_job[0], surv, "pubchem job chemical_id 未改指")
        self.assertEqual(pb_job[1], f"cid:{surv}:{cid_digest}",
                         "pubchem job dedupe_key 前缀未跟随 survivor(合并后任务迁移)")

    async def test_active_jobs_duplicate_collapsed(self):
        """rekey 撞 survivor 既有活跃键 → 吸收方任务行收敛(不并存双活)。"""
        from sqlalchemy import text
        from api.services.identity import absorb
        survivor = await self._chemical(cid=CID_A6 + 2, mol_smiles="CCO")
        absorbed = await self._chemical(cid=CID_A6 + 2)
        digest = hashlib.sha256(CAS.strip().encode()).hexdigest()[:16]
        async with self.Session() as db:
            for chem in (survivor, absorbed):
                await db.execute(text("""
                    INSERT INTO maintenance.cas_jobs
                      (chemical_id, cas_number, status, dedupe_key,
                       request_context)
                    VALUES (:c, :cas, 'queued', :dk, '{}'::jsonb)
                """), {"c": chem, "cas": CAS,
                       "dk": f"cas:{chem}:{digest}"})
            await db.commit()
            surv = await absorb(db, source_id=absorbed, target_id=survivor,
                                reason="cx-a6b", trigger=TRIGGER)
            await db.commit()
            rows = (await db.execute(text("""
                SELECT chemical_id, dedupe_key FROM maintenance.cas_jobs
                WHERE cas_number=:cas
            """), {"cas": CAS})).fetchall()
        self.assertEqual(len(rows), 1,
                         "合并后同 CAS 双活跃任务并存, 实际 %d 行" % len(rows))
        self.assertEqual(rows[0][0], surv)
        self.assertEqual(rows[0][1], f"cas:{surv}:{digest}")


if __name__ == "__main__":
    unittest.main()
