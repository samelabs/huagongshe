"""workapi 内部队列服务层 — 自 api/workapi.py 下沉, 逻辑零改动(批次3d)。

包含: lease_hash/verified_lease(租约校验), as_json_object/sync_chemical_core/
reject_completed_job/upsert_details(PB 完成写库),
verified_cas_lease/_cb_requery_days(CB 租约校验)。
外部引用者: api/workapi.py 各端点。
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text

from ..schemas.workapi import LeaseProof
from ..services.name_index import ingest_from_synonyms
from ..pubchem_core import chemical_core_values, number_or_none

def lease_hash(value: str) -> bytes:
    return hashlib.sha256(value.encode()).digest()


async def verified_lease(db: Any, proof: LeaseProof, worker_id: str, *, lock: bool = True):
    suffix = " FOR UPDATE" if lock else ""
    row = (await db.execute(text(f"""
        SELECT id,chemical_id,query_kind,query_value,sections,attempt_count,max_attempts
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
) -> None:
    """Synchronize trusted PubChem core fields without changing identity/structure."""
    values = chemical_core_values(properties, record_title=record_title)
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
                   CAST(:synonyms AS jsonb) AS synonyms
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
            (incoming.sync_synonyms AND chemistry.chemicals.synonyms IS DISTINCT FROM incoming.synonyms)
        )
    """), {
        "chemical_id": chemical_id,
        "sync_synonyms": synonyms is not None,
        "synonyms": json.dumps(synonyms, ensure_ascii=False, separators=(",", ":"))
        if synonyms is not None else None,
        **values,
    })
    # name_index 摄入: synonyms 镜像, 与核心列同步同事务
    if synonyms is not None:
        await ingest_from_synonyms(db, chemical_id, synonyms)


async def reject_completed_job(
    db: Any, job_id: int, worker_id: str, code: str, detail: str
) -> None:
    await db.execute(text("""
        UPDATE maintenance.pubchem_jobs
        SET status='failed',last_error_code=:code,last_error_detail=:detail,
            lease_owner=NULL,lease_token_hash=NULL,lease_expires_at=NULL,
            heartbeat_at=NULL,updated_at=now(),completed_at=now()
        WHERE id=:job_id
    """), {"job_id": job_id, "code": code, "detail": detail[:2000]})
    await db.execute(text("""
        INSERT INTO maintenance.pubchem_job_events(job_id,worker_id,event_type,details)
        VALUES (:job_id,:worker_id,'failed',jsonb_build_object(
            'code',CAST(:code AS text)))
    """), {"job_id": job_id, "worker_id": worker_id, "code": code})


async def upsert_details(
    db: Any,
    chemical_id: int,
    properties: dict[str, Any],
    sections: dict[str, Any],
    result: dict[str, Any],
) -> None:
    existing = (await db.execute(text("""
        SELECT * FROM chemistry.chemical_pubchem WHERE chemical_id=:chemical_id FOR UPDATE
    """), {"chemical_id": chemical_id})).mappings().fetchone()
    current = dict(existing) if existing else {}
    now_iso = datetime.now(timezone.utc).isoformat()
    fetched_sections = set(current.get("fetched_sections") or [])
    fetched_sections.update(sections)
    section_times = dict(current.get("section_fetched_at") or {})
    section_times.update({section: now_iso for section in sections})
    section_hashes = dict(current.get("section_source_hashes") or {})
    result_source_hash = str(result.get("source_hash") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", result_source_hash, re.I):
        result_source_hash = hashlib.sha256(
            json.dumps(result, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
    section_hashes.update({section: result_source_hash for section in sections})
    references = dict(current.get("source_references") or {})
    for section_name, section in sections.items():
        if isinstance(section, dict):
            # PUG View reference numbers are scoped to one response.  Keeping
            # them per section prevents an unrelated response from overwriting
            # a reference with the same numeric key.
            references[section_name] = as_json_object(section.get("references"))

    parsed_times: list[datetime] = []
    for raw in section_times.values():
        if not isinstance(raw, str):
            continue
        try:
            value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        parsed_times.append(value if value.tzinfo else value.replace(tzinfo=timezone.utc))
    # 与enrichment新鲜窗口同步30→100天(2026-08-30): 详情页按此字段判陈旧。
    expires_at = min(parsed_times) + timedelta(days=100) if parsed_times else None

    values = {
        "chemical_id": chemical_id,
        "record_title": result.get("record_title") or current.get("record_title"),
        "record_description": result.get("record_description") or current.get("record_description"),
        "xlogp": number_or_none(properties.get("XLogP")) if "XLogP" in properties else current.get("xlogp"),
        "tpsa": number_or_none(properties.get("TPSA")) if "TPSA" in properties else current.get("topological_polar_surface_area"),
        "complexity": number_or_none(properties.get("Complexity")) if "Complexity" in properties else current.get("complexity"),
        "hbd": number_or_none(properties.get("HBondDonorCount"), int) if "HBondDonorCount" in properties else current.get("hbond_donor_count"),
        "hba": number_or_none(properties.get("HBondAcceptorCount"), int) if "HBondAcceptorCount" in properties else current.get("hbond_acceptor_count"),
        "rotatable": number_or_none(properties.get("RotatableBondCount"), int) if "RotatableBondCount" in properties else current.get("rotatable_bond_count"),
        "heavy": number_or_none(properties.get("HeavyAtomCount"), int) if "HeavyAtomCount" in properties else current.get("heavy_atom_count"),
        "charge": number_or_none(properties.get("Charge"), int) if "Charge" in properties else current.get("formal_charge"),
        "computed": as_json_object(sections.get("computed")) or current.get("computed_properties", {}),
        "physical": as_json_object(sections.get("physical")) or current.get("physical_properties", {}),
        "ghs": as_json_object(as_json_object(sections.get("safety")).get("ghs")) or current.get("ghs_classification", {}),
        "hazards": as_json_object(as_json_object(sections.get("safety")).get("hazards")) or current.get("hazards", {}),
        "measures": as_json_object(as_json_object(sections.get("safety")).get("measures")) or current.get("safety_measures", {}),
        "toxicity": as_json_object(sections.get("toxicity")) or current.get("toxicity", {}),
        "regulatory": as_json_object(sections.get("regulatory")) or current.get("regulatory", {}),
        "pharmacology": as_json_object(sections.get("pharmacology")) or current.get("pharmacology", {}),
        "uses": as_json_object(sections.get("uses")) or current.get("uses_and_manufacturing", {}),
        "identifiers": as_json_object(sections.get("identifiers")) or current.get("identifier_evidence", {}),
        "references": references,
        "fetched_sections": sorted(fetched_sections),
        "section_times": section_times,
        "created_on": result.get("pubchem_created_on") or current.get("pubchem_created_on"),
        "modified_on": result.get("pubchem_modified_on") or current.get("pubchem_modified_on"),
        "source_hash": result_source_hash,
        "section_hashes": section_hashes,
        "expires_at": expires_at,
    }
    json_keys = (
        "computed", "physical", "ghs", "hazards", "measures", "toxicity",
        "regulatory", "pharmacology", "uses", "identifiers", "references",
        "section_times", "section_hashes",
    )
    params = dict(values)
    for key in json_keys:
        params[key] = json.dumps(values[key], ensure_ascii=False, separators=(",", ":"))
    await db.execute(text("""
        INSERT INTO chemistry.chemical_pubchem (
            chemical_id,record_title,record_description,xlogp,
            topological_polar_surface_area,complexity,hbond_donor_count,
            hbond_acceptor_count,rotatable_bond_count,heavy_atom_count,formal_charge,
            computed_properties,physical_properties,ghs_classification,hazards,
            safety_measures,toxicity,regulatory,pharmacology,uses_and_manufacturing,
            identifier_evidence,source_references,fetched_sections,section_fetched_at,
            section_source_hashes,
            pubchem_created_on,pubchem_modified_on,source_hash,schema_version,
            fetched_at,expires_at,updated_at
        ) VALUES (
            :chemical_id,:record_title,:record_description,:xlogp,:tpsa,:complexity,
            :hbd,:hba,:rotatable,:heavy,:charge,CAST(:computed AS jsonb),
            CAST(:physical AS jsonb),CAST(:ghs AS jsonb),CAST(:hazards AS jsonb),
            CAST(:measures AS jsonb),CAST(:toxicity AS jsonb),CAST(:regulatory AS jsonb),
            CAST(:pharmacology AS jsonb),CAST(:uses AS jsonb),CAST(:identifiers AS jsonb),
            CAST(:references AS jsonb),:fetched_sections,CAST(:section_times AS jsonb),
            CAST(:section_hashes AS jsonb),
            :created_on,:modified_on,:source_hash,1,now(),:expires_at,now()
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
            fetched_sections=excluded.fetched_sections,
            section_fetched_at=excluded.section_fetched_at,
            section_source_hashes=excluded.section_source_hashes,
            pubchem_created_on=excluded.pubchem_created_on,
            pubchem_modified_on=excluded.pubchem_modified_on,
            source_hash=excluded.source_hash,
            schema_version=excluded.schema_version,
            fetched_at=excluded.fetched_at,
            expires_at=excluded.expires_at,
            updated_at=excluded.updated_at
    """), params)

async def verified_cas_lease(db: Any, proof: LeaseProof, worker_id: str, *, lock: bool = True):
    suffix = " FOR UPDATE" if lock else ""
    row = (await db.execute(text(f"""
        SELECT id,chemical_id,cas_number,attempt_count,max_attempts
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


async def _cb_requery_days(db: Any) -> int:
    """lease 拦截窗口(读配置, 缺省180)。与 cas_externals._cb_window_days 同源语义。"""
    try:
        row = (await db.execute(text("""
            SELECT value FROM community.system_config
            WHERE namespace='cb' AND key='not_found_requery_days'
        """))).first()
        return int(row[0].get("days", 180)) if row else 180
    except Exception:
        return 180
