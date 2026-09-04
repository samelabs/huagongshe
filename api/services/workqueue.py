"""workapi 内部队列服务层 — 自 api/workapi.py 下沉, 逻辑零改动(批次3d)。

包含: lease_hash/verified_lease(租约校验), as_json_object/sync_chemical_core/
reject_completed_job/upsert_details(PB 完成写库),
verified_cas_lease(CB 租约校验)。
外部引用者: api/workapi.py 各端点。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text

from ..schemas.workapi import LeaseProof
from ..services.name_index import ingest_from_synonyms
from ..pubchem_core import chemical_core_values, number_or_none, validate_synonyms

def lease_hash(value: str) -> bytes:
    return hashlib.sha256(value.encode()).digest()


async def verified_lease(db: Any, proof: LeaseProof, worker_id: str, *, lock: bool = True):
    suffix = " FOR UPDATE" if lock else ""
    row = (await db.execute(text(f"""
        SELECT id,chemical_id,query_value
        FROM maintenance.pubchem_jobs
        WHERE id=:job_id AND status='leased' AND lease_owner=:worker_id
          AND lease_token_hash=:lease_hash AND lease_expires_at>now(){suffix}
    """), {
        "job_id": proof.job_id,
        "worker_id": worker_id,
        "lease_hash": lease_hash(proof.lease_token),
    })).fetchone()
    if not row:
        raise HTTPException(409, "lease is missing, expired, or owned by another worker")
    return row

def as_json_object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


async def sync_chemical_core(
    db: Any,
    chemical_id: int,
    properties: dict[str, Any],
    *,
    record_title: Any = None,
    synonyms: list[str] | None = None,
    cas_numbers: list[str] | None = None,
    main_table_ids: dict[str, list[str]] | None = None,
) -> None:
    """Synchronize trusted PubChem core fields without changing identity/structure.
    cas_numbers(0901 裁定): cb_number 为空才写(并集补空), 有 CB 印记归 CB 链。
    main_table_ids: nikkaji/chembl/ec/unii/chebi/dtxsid 主表已有列补空(0901 方案§四)。"""
    values = chemical_core_values(properties, record_title=record_title)
    id_arrays = {
        "nikkaji_numbers": (main_table_ids or {}).get("nikkaji_numbers"),
        "chembl_ids": (main_table_ids or {}).get("chembl_ids"),
        "ec_numbers": (main_table_ids or {}).get("ec_numbers"),
        "unii_codes": (main_table_ids or {}).get("unii_codes"),
        "chebi_ids": (main_table_ids or {}).get("chebi_ids"),
    }
    id_sets = {k: sorted(set(v)) for k, v in id_arrays.items() if v}
    dtxsid_values = sorted(set((main_table_ids or {}).get("dtxsid") or []))
    dtxsid_in = dtxsid_values[0] if dtxsid_values else None
    await db.execute(text("""
        WITH incoming AS (
            SELECT CAST(:preferred_name AS text) AS preferred_name,
                   CAST(:iupac_name AS text) AS iupac_name,
                   CAST(:molecular_formula AS text) AS molecular_formula,
                   CAST(:average_mass AS double precision) AS average_mass,
                   CAST(:monoisotopic_mass AS double precision) AS monoisotopic_mass,
                   CAST(:inchikey AS text) AS inchikey,
                   CAST(:pubchem_cid AS integer) AS pubchem_cid,
                   CAST(:pubchem_smiles AS text) AS pubchem_smiles,
                   CAST(:sync_synonyms AS boolean) AS sync_synonyms,
                   CAST(:synonyms AS jsonb) AS synonyms,
                   CAST(:cas_in AS text[]) AS cas_in,
                   CAST(:nikkaji_in AS text[]) AS nikkaji_in,
                   CAST(:chembl_in AS text[]) AS chembl_in,
                   CAST(:ec_in AS text[]) AS ec_in,
                   CAST(:unii_in AS text[]) AS unii_in,
                   CAST(:chebi_in AS text[]) AS chebi_in,
                   CAST(:dtxsid_in AS text) AS dtxsid_in
        )
        UPDATE chemistry.chemicals
        SET preferred_name=coalesce(incoming.preferred_name,chemistry.chemicals.preferred_name),
            iupac_name=coalesce(incoming.iupac_name,chemistry.chemicals.iupac_name),
            molecular_formula=coalesce(incoming.molecular_formula,chemistry.chemicals.molecular_formula),
            average_mass=coalesce(incoming.average_mass,chemistry.chemicals.average_mass),
            monoisotopic_mass=coalesce(incoming.monoisotopic_mass,chemistry.chemicals.monoisotopic_mass),
            inchikey=coalesce(incoming.inchikey,chemistry.chemicals.inchikey),
            pubchem_cid=coalesce(incoming.pubchem_cid,chemistry.chemicals.pubchem_cid),
            pubchem_smiles=coalesce(incoming.pubchem_smiles,chemistry.chemicals.pubchem_smiles),
            synonyms=CASE WHEN incoming.sync_synonyms
                THEN incoming.synonyms ELSE chemistry.chemicals.synonyms END,
            cas_numbers=CASE
                WHEN chemistry.chemicals.cb_number IS NULL
                 AND cardinality(incoming.cas_in) > 0
                THEN coalesce(chemistry.chemicals.cas_numbers, ARRAY[]::text[])
                     || (SELECT array_agg(DISTINCT c) FROM unnest(incoming.cas_in) c
                         WHERE NOT coalesce(chemistry.chemicals.cas_numbers, ARRAY[]::text[]) @> ARRAY[c])
                ELSE chemistry.chemicals.cas_numbers END,
            nikkaji_numbers=CASE WHEN cardinality(incoming.nikkaji_in) > 0
                THEN coalesce(chemistry.chemicals.nikkaji_numbers, incoming.nikkaji_in)
                ELSE chemistry.chemicals.nikkaji_numbers END,
            chembl_ids=CASE WHEN cardinality(incoming.chembl_in) > 0
                THEN coalesce(chemistry.chemicals.chembl_ids, incoming.chembl_in)
                ELSE chemistry.chemicals.chembl_ids END,
            ec_numbers=CASE WHEN cardinality(incoming.ec_in) > 0
                THEN coalesce(chemistry.chemicals.ec_numbers, incoming.ec_in)
                ELSE chemistry.chemicals.ec_numbers END,
            unii_codes=CASE WHEN cardinality(incoming.unii_in) > 0
                THEN coalesce(chemistry.chemicals.unii_codes, incoming.unii_in)
                ELSE chemistry.chemicals.unii_codes END,
            chebi_ids=CASE WHEN cardinality(incoming.chebi_in) > 0
                THEN coalesce(chemistry.chemicals.chebi_ids, incoming.chebi_in)
                ELSE chemistry.chemicals.chebi_ids END,
            dtxsid=CASE WHEN incoming.dtxsid_in IS NOT NULL
                 AND NOT EXISTS (SELECT 1 FROM chemistry.chemicals c2
                     WHERE c2.dtxsid=incoming.dtxsid_in AND c2.id<>:chemical_id)
                THEN coalesce(chemistry.chemicals.dtxsid, incoming.dtxsid_in)
                ELSE chemistry.chemicals.dtxsid END,
            updated_at=now()
        FROM incoming
        WHERE chemistry.chemicals.id=:chemical_id AND (
            (incoming.preferred_name IS NOT NULL AND chemistry.chemicals.preferred_name IS DISTINCT FROM incoming.preferred_name) OR
            (incoming.iupac_name IS NOT NULL AND chemistry.chemicals.iupac_name IS DISTINCT FROM incoming.iupac_name) OR
            (incoming.molecular_formula IS NOT NULL AND chemistry.chemicals.molecular_formula IS DISTINCT FROM incoming.molecular_formula) OR
            (incoming.average_mass IS NOT NULL AND chemistry.chemicals.average_mass IS DISTINCT FROM incoming.average_mass) OR
            (incoming.monoisotopic_mass IS NOT NULL AND chemistry.chemicals.monoisotopic_mass IS DISTINCT FROM incoming.monoisotopic_mass) OR
            (incoming.inchikey IS NOT NULL AND chemistry.chemicals.inchikey IS DISTINCT FROM incoming.inchikey) OR
            (incoming.pubchem_cid IS NOT NULL AND chemistry.chemicals.pubchem_cid IS DISTINCT FROM incoming.pubchem_cid) OR
            (incoming.pubchem_smiles IS NOT NULL AND chemistry.chemicals.pubchem_smiles IS DISTINCT FROM incoming.pubchem_smiles) OR
            (incoming.sync_synonyms AND chemistry.chemicals.synonyms IS DISTINCT FROM incoming.synonyms) OR
            (chemistry.chemicals.cb_number IS NULL AND cardinality(incoming.cas_in) > 0
             AND NOT coalesce(chemistry.chemicals.cas_numbers, ARRAY[]::text[]) @> incoming.cas_in) OR
            (cardinality(incoming.nikkaji_in) > 0
             AND (chemistry.chemicals.nikkaji_numbers IS NULL OR chemistry.chemicals.nikkaji_numbers <> incoming.nikkaji_in)) OR
            (cardinality(incoming.chembl_in) > 0
             AND (chemistry.chemicals.chembl_ids IS NULL OR chemistry.chemicals.chembl_ids <> incoming.chembl_in)) OR
            (cardinality(incoming.ec_in) > 0
             AND (chemistry.chemicals.ec_numbers IS NULL OR chemistry.chemicals.ec_numbers <> incoming.ec_in)) OR
            (cardinality(incoming.unii_in) > 0
             AND (chemistry.chemicals.unii_codes IS NULL OR chemistry.chemicals.unii_codes <> incoming.unii_in)) OR
            (cardinality(incoming.chebi_in) > 0
             AND (chemistry.chemicals.chebi_ids IS NULL OR chemistry.chemicals.chebi_ids <> incoming.chebi_in)) OR
            (incoming.dtxsid_in IS NOT NULL AND chemistry.chemicals.dtxsid IS DISTINCT FROM incoming.dtxsid_in)
        )
    """), {
        "chemical_id": chemical_id,
        "sync_synonyms": synonyms is not None,
        # 0904: validate_synonyms 原是四层重构孤儿(全库零引用)。它是 PB
        # synonyms 上限防线(20万条/8MB), 接回写入口 — 校验失败返回 None 不写。
        "synonyms": (
            json.dumps(validated, ensure_ascii=False, separators=(",", ":"))
            if (validated := (validate_synonyms(synonyms) if synonyms is not None else None)) is not None
            else None
        ),
        "cas_in": cas_numbers or [],
        "nikkaji_in": id_sets.get("nikkaji_numbers", []),
        "chembl_in": id_sets.get("chembl_ids", []),
        "ec_in": id_sets.get("ec_numbers", []),
        "unii_in": id_sets.get("unii_codes", []),
        "chebi_in": id_sets.get("chebi_ids", []),
        "dtxsid_in": dtxsid_in,
        **values,
    })
    # name_index 摄入: synonyms 镜像, 与核心列同步同事务
    if synonyms is not None:
        await ingest_from_synonyms(db, chemical_id, synonyms)


async def upsert_details(
    db: Any,
    chemical_id: int,
    payload: dict[str, Any],
) -> None:
    """整包入库(0901 定案): 拉到就 update 全字段覆盖, fetched_at=now()。
    payload = worker 整包解析产物(结构化字段), 无 merge 无校验。"""
    def obj(key: str) -> str:
        return json.dumps(as_json_object(payload.get(key)), ensure_ascii=False, separators=(",", ":"))

    def num(key: str, cast=float):
        return number_or_none(payload.get(key), cast)

    from datetime import date as _date
    def as_date(key: str):
        raw = payload.get(key)
        if raw is None or isinstance(raw, _date):
            return raw
        try:
            return _date.fromisoformat(str(raw)[:10])
        except ValueError:
            return None

    params = {
        "chemical_id": chemical_id,
        "record_title": payload.get("record_title"),
        "record_description": payload.get("record_description"),
        "xlogp": num("xlogp"), "tpsa": num("tpsa"), "complexity": num("complexity"),
        "hbd": num("hbd", int), "hba": num("hba", int), "rotatable": num("rotatable", int),
        "heavy": num("heavy", int), "charge": num("charge", int),
        "computed": obj("computed"), "physical": obj("physical"),
        "ghs": obj("ghs"), "hazards": obj("hazards"), "measures": obj("measures"),
        "toxicity": obj("toxicity"), "regulatory": obj("regulatory"),
        "pharmacology": obj("pharmacology"), "uses": obj("uses"),
        "identifiers": obj("identifiers"), "references": obj("references"),
        "external_ids": obj("external_ids"), "ghs_codes": obj("ghs_codes"),
        "exp_props": obj("exp_props"), "exp_limits": obj("exp_limits"),
        "reactivity": obj("reactivity"),
        "created_on": as_date("pubchem_created_on"),
        "modified_on": as_date("pubchem_modified_on"),
    }
    await db.execute(text("""
        INSERT INTO chemistry.chemical_pubchem (
            chemical_id,record_title,record_description,xlogp,
            topological_polar_surface_area,complexity,hbond_donor_count,
            hbond_acceptor_count,rotatable_bond_count,heavy_atom_count,formal_charge,
            computed_properties,physical_properties,ghs_classification,hazards,
            safety_measures,toxicity,regulatory,pharmacology,uses_and_manufacturing,
            identifier_evidence,source_references,
            external_ids,ghs_codes,exp_props,exp_limits,reactivity,
            pubchem_created_on,pubchem_modified_on,
            fetched_at,updated_at
        ) VALUES (
            :chemical_id,:record_title,:record_description,:xlogp,
            :tpsa,:complexity,:hbd,:hba,:rotatable,:heavy,:charge,
            CAST(:computed AS jsonb),CAST(:physical AS jsonb),CAST(:ghs AS jsonb),
            CAST(:hazards AS jsonb),CAST(:measures AS jsonb),CAST(:toxicity AS jsonb),
            CAST(:regulatory AS jsonb),CAST(:pharmacology AS jsonb),CAST(:uses AS jsonb),
            CAST(:identifiers AS jsonb),CAST(:references AS jsonb),
            CAST(:external_ids AS jsonb),CAST(:ghs_codes AS jsonb),
            CAST(:exp_props AS jsonb),CAST(:exp_limits AS jsonb),CAST(:reactivity AS jsonb),
            :created_on,:modified_on,
            now(),now()
        )
        ON CONFLICT (chemical_id) DO UPDATE SET
            record_title=excluded.record_title,
            record_description=excluded.record_description,
            xlogp=excluded.xlogp,
            topological_polar_surface_area=excluded.topological_polar_surface_area,
            complexity=excluded.complexity,
            hbond_donor_count=excluded.hbond_donor_count,
            hbond_acceptor_count=excluded.hbond_acceptor_count,
            rotatable_bond_count=excluded.rotatable_bond_count,
            heavy_atom_count=excluded.heavy_atom_count,
            formal_charge=excluded.formal_charge,
            computed_properties=excluded.computed_properties,
            physical_properties=excluded.physical_properties,
            ghs_classification=excluded.ghs_classification,
            hazards=excluded.hazards,
            safety_measures=excluded.safety_measures,
            toxicity=excluded.toxicity,
            regulatory=excluded.regulatory,
            pharmacology=excluded.pharmacology,
            uses_and_manufacturing=excluded.uses_and_manufacturing,
            identifier_evidence=excluded.identifier_evidence,
            source_references=excluded.source_references,
            external_ids=excluded.external_ids,
            ghs_codes=excluded.ghs_codes,
            exp_props=excluded.exp_props,
            exp_limits=excluded.exp_limits,
            reactivity=excluded.reactivity,
            pubchem_created_on=excluded.pubchem_created_on,
            pubchem_modified_on=excluded.pubchem_modified_on,
            fetched_at=excluded.fetched_at,
            updated_at=excluded.updated_at
    """), params)

async def verified_cas_lease(db: Any, proof: LeaseProof, worker_id: str, *, lock: bool = True):
    suffix = " FOR UPDATE" if lock else ""
    row = (await db.execute(text(f"""
        SELECT id,chemical_id,cas_number
        FROM maintenance.cas_jobs
        WHERE id=:job_id AND status='leased' AND lease_owner=:worker_id
          AND lease_token_hash=:lease_hash AND lease_expires_at>now(){suffix}
    """), {
        "job_id": proof.job_id,
        "worker_id": worker_id,
        "lease_hash": lease_hash(proof.lease_token),
    })).fetchone()
    if not row:
        raise HTTPException(409, "lease is missing, expired, or owned by another worker")
    return row
