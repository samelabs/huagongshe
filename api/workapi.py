"""Authenticated POST-only maintenance API used by the PubChem worker."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from .cache import cache_delete, get_cache
from .config import settings
from .database import get_db
from .name_index import ingest_from_synonyms
from .pubchem_core import chemical_core_values, number_or_none, validate_synonyms

router = APIRouter(prefix="/workapi/v1", tags=["workapi"])

NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


@dataclass(frozen=True)
class WorkerContext:
    worker_id: str
    max_lease_jobs: int


class LeaseBody(BaseModel):
    max_jobs: int = Field(default=2, ge=1, le=20)
    capabilities: list[str] = Field(default_factory=lambda: ["pubchem"], max_length=20)


class LeaseProof(BaseModel):
    job_id: int = Field(gt=0)
    lease_token: str = Field(min_length=32, max_length=256)


class CompleteBody(LeaseProof):
    result: dict[str, Any]


class FailBody(LeaseProof):
    error_code: str = Field(min_length=1, max_length=100)
    error_detail: str = Field(default="", max_length=2000)
    retryable: bool = True
    retry_after_seconds: int = Field(default=30, ge=1, le=3600)


async def authenticated_worker(
    request: Request,
    db=Depends(get_db),
    authorization: str | None = Header(default=None),
    x_worker_id: str | None = Header(default=None),
    x_work_timestamp: str | None = Header(default=None),
    x_work_nonce: str | None = Header(default=None),
    x_work_signature: str | None = Header(default=None),
) -> WorkerContext:
    body = await request.body()
    if len(body) > settings.worker_max_body_bytes:
        raise HTTPException(413, "worker payload too large")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing worker token")
    token = authorization[7:].strip()
    if len(token) < 32 or not x_worker_id:
        raise HTTPException(401, "invalid worker identity")
    try:
        timestamp = int(x_work_timestamp or "")
    except ValueError as exc:
        raise HTTPException(401, "invalid worker timestamp") from exc
    if abs(int(time.time()) - timestamp) > settings.worker_signature_skew_seconds:
        raise HTTPException(401, "expired worker signature")
    if not x_work_nonce or not NONCE_RE.fullmatch(x_work_nonce):
        raise HTTPException(401, "invalid worker nonce")

    body_hash = hashlib.sha256(body).hexdigest()
    signed = "\n".join(
        (str(timestamp), x_work_nonce, request.method.upper(), request.url.path, body_hash)
    ).encode()
    expected = hmac.new(token.encode(), signed, hashlib.sha256).hexdigest()
    if not x_work_signature or not hmac.compare_digest(expected, x_work_signature.lower()):
        raise HTTPException(401, "invalid worker signature")

    token_hash = hashlib.sha256(token.encode()).digest()
    scope_needed = "cas" if request.url.path.startswith("/workapi/v1/cas/") else "pubchem"
    row = (await db.execute(text(f"""
        SELECT worker_id,max_lease_jobs
        FROM maintenance.worker_clients
        WHERE worker_id=:worker_id AND token_hash=:token_hash
          AND enabled AND disabled_at IS NULL AND :scope=ANY(scopes)
    """), {"worker_id": x_worker_id, "token_hash": token_hash, "scope": scope_needed})).fetchone()
    if not row:
        raise HTTPException(401, "unknown or disabled worker")

    redis = await get_cache()
    nonce_key = f"workapi:nonce:{x_worker_id}:{x_work_nonce}"
    try:
        accepted = await redis.set(nonce_key, "1", ex=600, nx=True)
    except Exception as exc:
        raise HTTPException(503, "worker replay protection unavailable") from exc
    if not accepted:
        raise HTTPException(409, "replayed worker request")
    # The worker calls this API throughout a task. Throttle last-seen
    # persistence so heartbeats do not create avoidable WAL churn.
    seen_key = f"workapi:last-seen:{x_worker_id}"
    if await redis.set(seen_key, "1", ex=300, nx=True):
        await db.execute(text("""
            UPDATE maintenance.worker_clients
            SET last_seen_at=now() WHERE worker_id=:worker_id
        """), {"worker_id": x_worker_id})
    return WorkerContext(str(row[0]), int(row[1]))


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


@router.post("/jobs/lease")
async def lease_jobs(
    body: LeaseBody,
    db=Depends(get_db),
    worker: WorkerContext = Depends(authenticated_worker),
):
    limit = min(body.max_jobs, worker.max_lease_jobs)
    if "pubchem" not in body.capabilities:
        await db.commit()
        return {"jobs": [], "retry_after_seconds": 30}
    try:
        redis = await get_cache()
        if await redis.set("pubchem:jobs:prune", "1", ex=3600, nx=True):
            # Bounded retention keeps the durable queue auditable without
            # allowing successful task/event history to grow forever.
            await db.execute(text("""
                DELETE FROM maintenance.pubchem_jobs
                WHERE id IN (
                    SELECT id FROM maintenance.pubchem_jobs
                    WHERE completed_at IS NOT NULL AND (
                        (status='succeeded' AND completed_at<now()-interval '30 days') OR
                        (status IN ('failed','dead') AND completed_at<now()-interval '90 days')
                    )
                    ORDER BY completed_at,id LIMIT 5000
                )
            """))
        await db.execute(text("""
            UPDATE maintenance.pubchem_jobs
            SET status=CASE WHEN attempt_count>=max_attempts THEN 'dead' ELSE 'retry' END,
                not_before=CASE WHEN attempt_count>=max_attempts THEN not_before ELSE now() END,
                lease_owner=NULL,lease_token_hash=NULL,lease_expires_at=NULL,
                heartbeat_at=NULL,updated_at=now(),
                completed_at=CASE WHEN attempt_count>=max_attempts THEN now() ELSE completed_at END,
                last_error_code='lease_expired'
            WHERE status='leased' AND lease_expires_at<=now()
        """))
        rows = (await db.execute(text("""
            SELECT j.id,j.chemical_id,j.query_kind,j.query_value,j.sections,
                   j.attempt_count,j.max_attempts,c.pubchem_cid,c.smiles
            FROM maintenance.pubchem_jobs j
            LEFT JOIN chemistry.chemicals c ON c.id=j.chemical_id
            WHERE j.status IN ('queued','retry') AND j.not_before<=now()
              AND j.attempt_count<j.max_attempts
            ORDER BY j.priority DESC,j.not_before,j.id
            LIMIT :limit FOR UPDATE OF j SKIP LOCKED
        """), {"limit": limit})).fetchall()
        leased = []
        for row in rows:
            token = secrets.token_urlsafe(32)
            await db.execute(text("""
                UPDATE maintenance.pubchem_jobs
                SET status='leased',lease_owner=:worker_id,lease_token_hash=:token_hash,
                    lease_expires_at=now()+make_interval(secs=>:lease_seconds),
                    heartbeat_at=now(),attempt_count=attempt_count+1,updated_at=now()
                WHERE id=:job_id
            """), {
                "worker_id": worker.worker_id,
                "token_hash": lease_hash(token),
                "lease_seconds": settings.worker_job_lease_seconds,
                "job_id": row[0],
            })
            await db.execute(text("""
                INSERT INTO maintenance.pubchem_job_events(job_id,worker_id,event_type,details)
                VALUES (:job_id,:worker_id,'leased',jsonb_build_object(
                    'attempt',CAST(:attempt AS integer)))
            """), {
                "job_id": row[0], "worker_id": worker.worker_id, "attempt": row[5] + 1,
            })
            leased.append({
                "job_id": row[0],
                "lease_token": token,
                "chemical_id": row[1],
                "query_kind": row[2],
                "query_value": row[3],
                "sections": list(row[4] or []),
                "attempt": row[5] + 1,
                "max_attempts": row[6],
                "expected_pubchem_cid": row[7],
                "expected_smiles": row[8],
                "lease_seconds": settings.worker_job_lease_seconds,
            })
        await db.commit()
        return {"jobs": leased, "retry_after_seconds": 2 if leased else 5}
    except Exception:
        await db.rollback()
        raise


@router.post("/jobs/heartbeat")
async def heartbeat(
    body: LeaseProof,
    db=Depends(get_db),
    worker: WorkerContext = Depends(authenticated_worker),
):
    try:
        await verified_lease(db, body, worker.worker_id)
        await db.execute(text("""
            UPDATE maintenance.pubchem_jobs
            SET heartbeat_at=now(),lease_expires_at=now()+make_interval(secs=>:seconds),
                updated_at=now() WHERE id=:job_id
        """), {"seconds": settings.worker_job_lease_seconds, "job_id": body.job_id})
        await db.commit()
        return {"status": "leased", "lease_seconds": settings.worker_job_lease_seconds}
    except Exception:
        await db.rollback()
        raise


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
        SELECT * FROM chemistry.chemical_details WHERE chemical_id=:chemical_id FOR UPDATE
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
    expires_at = min(parsed_times) + timedelta(days=30) if parsed_times else None

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
        INSERT INTO chemistry.chemical_details (
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


@router.post("/jobs/complete")
async def complete_job(
    body: CompleteBody,
    db=Depends(get_db),
    worker: WorkerContext = Depends(authenticated_worker),
):
    try:
        job = await verified_lease(db, body, worker.worker_id)
        result = body.result
        candidates = result.get("candidates") if isinstance(result.get("candidates"), list) else []
        properties = as_json_object(result.get("properties"))
        selected_cid = number_or_none(result.get("selected_cid"), int)
        if selected_cid is not None and selected_cid <= 0:
            selected_cid = None
        chemical_id = job[1]
        if selected_cid is None:
            await reject_completed_job(
                db, body.job_id, worker.worker_id, "unresolved_cid",
                "worker did not resolve exactly one PubChem CID",
            )
            await db.commit()
            raise HTTPException(422, "worker did not resolve exactly one PubChem CID")

        candidate_cids = {
            number_or_none(item.get("CID"), int)
            for item in candidates
            if isinstance(item, dict)
        }
        candidate_cids.discard(None)
        if selected_cid not in candidate_cids:
            await reject_completed_job(
                db, body.job_id, worker.worker_id, "candidate_mismatch",
                "selected CID is absent from the returned property candidates",
            )
            await db.commit()
            raise HTTPException(422, "selected CID is absent from candidates")
        if job[2] == "cid" and str(selected_cid) != str(job[3]).strip():
            await reject_completed_job(
                db, body.job_id, worker.worker_id, "query_cid_mismatch",
                "selected CID differs from the CID job query",
            )
            await db.commit()
            raise HTTPException(422, "selected CID differs from query")

        chemical = None
        if chemical_id is not None:
            chemical = (await db.execute(text("""
                SELECT id,pubchem_cid,smiles,inchikey FROM chemistry.chemicals WHERE id=:id FOR UPDATE
            """), {"id": chemical_id})).fetchone()
            if not chemical:
                await reject_completed_job(db, body.job_id, worker.worker_id, "chemical_missing", "target chemical no longer exists")
                await db.commit()
                raise HTTPException(422, "target chemical no longer exists")
        elif selected_cid is not None:
            chemical = (await db.execute(text("""
                SELECT id,pubchem_cid,smiles,inchikey FROM chemistry.chemicals
                WHERE pubchem_cid=:cid ORDER BY id LIMIT 1 FOR UPDATE
            """), {"cid": selected_cid})).fetchone()
            if chemical:
                chemical_id = chemical[0]

        if chemical and selected_cid is not None:
            if chemical[1] is not None and int(chemical[1]) != selected_cid:
                await reject_completed_job(db, body.job_id, worker.worker_id, "cid_mismatch", "result CID differs from stored PubChem CID")
                await db.commit()
                raise HTTPException(422, "result CID differs from stored PubChem CID")
            returned_inchikey = properties.get("InChIKey")
            expected_inchikey = chemical[3]
            if returned_inchikey and expected_inchikey and returned_inchikey != expected_inchikey:
                await reject_completed_job(db, body.job_id, worker.worker_id, "structure_mismatch", "PubChem InChIKey differs from chemicals.inchikey")
                await db.commit()
                raise HTTPException(422, "PubChem InChIKey differs from chemicals.inchikey")

        allowed_for_job = set(job[4] or [])
        sections = as_json_object(result.get("sections"))
        sections = {key: value for key, value in sections.items() if key in {
            "computed", "identifiers", "synonyms", "physical", "safety", "toxicity",
            "regulatory", "pharmacology", "uses",
        } and key in allowed_for_job and isinstance(value, dict)}
        synonyms = None
        if "synonyms" in allowed_for_job:
            if "synonyms" not in sections:
                await reject_completed_job(
                    db, body.job_id, worker.worker_id, "synonyms_missing",
                    "worker omitted the requested PubChem synonym list",
                )
                await db.commit()
                raise HTTPException(422, "worker omitted requested synonyms")
            try:
                synonyms = validate_synonyms(sections["synonyms"].get("values"))
            except ValueError as exc:
                await reject_completed_job(
                    db, body.job_id, worker.worker_id, "synonyms_invalid", str(exc),
                )
                await db.commit()
                raise HTTPException(422, str(exc)) from exc
        if chemical_id is not None and selected_cid is not None:
            await sync_chemical_core(
                db,
                int(chemical_id),
                properties,
                record_title=result.get("record_title"),
                synonyms=synonyms,
            )
            await upsert_details(db, int(chemical_id), properties, sections, result)

        summary = {
            "selected_cid": selected_cid,
            "chemical_id": chemical_id,
            "candidate_count": len(candidates),
            "candidates": candidates[:10],
            "fetched_sections": sorted(sections),
        }
        result_hash = str(result.get("source_hash") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", result_hash, re.I):
            result_hash = hashlib.sha256(
                json.dumps(result, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()
        await db.execute(text("""
            UPDATE maintenance.pubchem_jobs
            SET status='succeeded',chemical_id=coalesce(chemical_id,:chemical_id),
                resolved_pubchem_cid=:cid,result_hash=:result_hash,
                result_summary=CAST(:summary AS jsonb),last_error_code=NULL,
                last_error_detail=NULL,lease_owner=NULL,lease_token_hash=NULL,
                lease_expires_at=NULL,heartbeat_at=NULL,updated_at=now(),completed_at=now()
            WHERE id=:job_id
        """), {
            "job_id": body.job_id,
            "chemical_id": chemical_id,
            "cid": selected_cid,
            "result_hash": result_hash,
            "summary": json.dumps(summary, ensure_ascii=False, separators=(",", ":")),
        })
        await db.execute(text("""
            INSERT INTO maintenance.pubchem_job_events(job_id,worker_id,event_type,details)
            VALUES (:job_id,:worker_id,'succeeded',jsonb_build_object(
                'chemical_id',CAST(:chemical_id AS integer),
                'pubchem_cid',CAST(:cid AS integer),
                'sections',CAST(:sections AS text[])))
        """), {
            "job_id": body.job_id, "worker_id": worker.worker_id,
            "chemical_id": chemical_id, "cid": selected_cid, "sections": list(sections),
        })
        await db.commit()
        if chemical_id is not None:
            await cache_delete(f"v1:chemical:{chemical_id}")
        return summary
    except HTTPException:
        raise
    except Exception:
        await db.rollback()
        raise


@router.post("/jobs/fail")
async def fail_job(
    body: FailBody,
    db=Depends(get_db),
    worker: WorkerContext = Depends(authenticated_worker),
):
    try:
        job = await verified_lease(db, body, worker.worker_id)
        retry = body.retryable and int(job[5]) < int(job[6])
        status = "retry" if retry else ("dead" if body.retryable else "failed")
        await db.execute(text("""
            UPDATE maintenance.pubchem_jobs
            SET status=:status,not_before=CASE WHEN :retry
                    THEN now()+make_interval(secs=>:retry_after) ELSE not_before END,
                last_error_code=:code,last_error_detail=:detail,
                lease_owner=NULL,lease_token_hash=NULL,lease_expires_at=NULL,
                heartbeat_at=NULL,updated_at=now(),
                completed_at=CASE WHEN :retry THEN NULL ELSE now() END
            WHERE id=:job_id
        """), {
            "status": status, "retry": retry, "retry_after": body.retry_after_seconds,
            "code": body.error_code, "detail": body.error_detail, "job_id": body.job_id,
        })
        await db.execute(text("""
            INSERT INTO maintenance.pubchem_job_events(job_id,worker_id,event_type,details)
            VALUES (:job_id,:worker_id,:event_type,
                    jsonb_build_object(
                        'code',CAST(:code AS text),
                        'retry_after',CAST(:retry_after AS integer)))
        """), {
            "job_id": body.job_id, "worker_id": worker.worker_id,
            "event_type": status, "code": body.error_code,
            "retry_after": body.retry_after_seconds,
        })
        await db.commit()
        return {"status": status}
    except Exception:
        await db.rollback()
        raise


# ---------------------------------------------------------------- cas jobs
# 与 pubchem jobs 同协议(HMAC/租约/心跳/nonce), 独立表 maintenance.cas_jobs。
# worker 认领时声明 capabilities=["cas"]; scopes 检查在 authenticated_worker。

class CasLeaseBody(BaseModel):
    max_jobs: int = Field(default=2, ge=1, le=20)
    capabilities: list[str] = Field(default_factory=lambda: ["cas"], max_length=20)


class CasResultBody(BaseModel):
    status: str = Field(pattern="^(ok|not_found)$")
    entry: dict[str, Any] | None = None
    suppliers: list[dict[str, Any]] = Field(default_factory=list)
    # CB molfile 原文(可选): 详情页有 MOL 外链时 worker 附带; 服务端只补空不覆盖
    mol: str | None = Field(default=None, max_length=1_000_000)


class CasCompleteBody(LeaseProof):
    result: CasResultBody


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


@router.post("/cas/jobs/lease")
async def cas_lease_jobs(
    body: CasLeaseBody,
    db=Depends(get_db),
    worker: WorkerContext = Depends(authenticated_worker),
):
    limit = min(body.max_jobs, worker.max_lease_jobs)
    if "cas" not in body.capabilities:
        await db.commit()
        return {"jobs": [], "retry_after_seconds": 30}
    try:
        # 到期自扫(替代 SSR 触发, CF 缓存场景同样生效) + 过期租约回收 + 留存清理
        from .cas_externals import scan_expired_into_queue
        await scan_expired_into_queue(db)
        await db.execute(text("""
            UPDATE maintenance.cas_jobs
            SET status=CASE WHEN attempt_count>=max_attempts THEN 'dead' ELSE 'retry' END,
                lease_owner=NULL,lease_token_hash=NULL,lease_expires_at=NULL,
                heartbeat_at=NULL,updated_at=now(),
                completed_at=CASE WHEN attempt_count>=max_attempts THEN now() ELSE completed_at END,
                last_error_code='lease_expired'
            WHERE status='leased' AND lease_expires_at<=now()
        """))
        await db.execute(text("""
            DELETE FROM maintenance.cas_jobs
            WHERE id IN (
                SELECT id FROM maintenance.cas_jobs
                WHERE completed_at IS NOT NULL AND (
                    (status='succeeded' AND completed_at<now()-interval '30 days') OR
                    (status IN ('failed','dead') AND completed_at<now()-interval '90 days')
                )
                ORDER BY completed_at,id LIMIT 5000
            )
        """))
        rows = (await db.execute(text("""
            SELECT id,chemical_id,cas_number,attempt_count,max_attempts
            FROM maintenance.cas_jobs
            WHERE status IN ('queued','retry') AND not_before<=now()
              AND attempt_count<max_attempts
            ORDER BY priority DESC,not_before,id
            LIMIT :limit FOR UPDATE SKIP LOCKED
        """), {"limit": limit})).fetchall()
        leased = []
        for row in rows:
            token = secrets.token_urlsafe(32)
            await db.execute(text("""
                UPDATE maintenance.cas_jobs
                SET status='leased',lease_owner=:worker_id,lease_token_hash=:token_hash,
                    lease_expires_at=now()+make_interval(secs=>:lease_seconds),
                    heartbeat_at=now(),attempt_count=attempt_count+1,updated_at=now()
                WHERE id=:job_id
            """), {
                "worker_id": worker.worker_id,
                "token_hash": lease_hash(token),
                "lease_seconds": settings.worker_job_lease_seconds,
                "job_id": row[0],
            })
            leased.append({
                "job_id": row[0],
                "lease_token": token,
                "chemical_id": row[1],
                "cas_number": row[2],
                "attempt": row[3] + 1,
                "max_attempts": row[4],
                "lease_seconds": settings.worker_job_lease_seconds,
            })
        await db.commit()
        return {"jobs": leased, "retry_after_seconds": 2 if leased else 10}
    except Exception:
        await db.rollback()
        raise


@router.post("/cas/jobs/heartbeat")
async def cas_heartbeat(
    body: LeaseProof,
    db=Depends(get_db),
    worker: WorkerContext = Depends(authenticated_worker),
):
    try:
        await verified_cas_lease(db, body, worker.worker_id, lock=False)
        await db.execute(text("""
            UPDATE maintenance.cas_jobs
            SET heartbeat_at=now(),lease_expires_at=now()+make_interval(secs=>:seconds),
                updated_at=now() WHERE id=:job_id
        """), {"seconds": settings.worker_job_lease_seconds, "job_id": body.job_id})
        await db.commit()
        return {"status": "leased", "lease_seconds": settings.worker_job_lease_seconds}
    except Exception:
        await db.rollback()
        raise


@router.post("/cas/jobs/complete")
async def cas_complete_job(
    body: CasCompleteBody,
    db=Depends(get_db),
    worker: WorkerContext = Depends(authenticated_worker),
):
    from .cas_externals import CACHE_KEY, apply_structure_fill, resolve_structure, upsert_externals
    try:
        job = await verified_cas_lease(db, body, worker.worker_id)
        chemical_id = job[1]
        cas_number = job[2]
        if chemical_id is None:
            # standalone 任务(搜索miss入队): CB ok -> 建最小行; not_found -> 负缓存。
            # 建行含同CAS查重(已存在则复用id); 不做跨行比对(2026-08-27定案)。
            payload = body.result
            entry = payload.entry if payload.status == "ok" else None
            if entry is not None:
                from .cas_externals import create_chemical_from_cb_entry
                chemical_id = await create_chemical_from_cb_entry(
                    db, cas_number=cas_number, entry=entry
                )
                # 结构三件只补空: cid 在的行 PubChem 早填过(coalesce no-op),
                # 真正受益者是 pubchem_cid=NULL 的 CB 行
                await apply_structure_fill(
                    db, chemical_id,
                    resolve_structure(entry, payload.mol),
                )
                await db.commit()
            else:
                await db.execute(text("""
                    UPDATE maintenance.cas_jobs
                    SET status='succeeded',result_summary=CAST(:summary AS jsonb),
                        lease_owner=NULL,lease_token_hash=NULL,lease_expires_at=NULL,
                        heartbeat_at=NULL,updated_at=now(),completed_at=now()
                    WHERE id=:job_id
                """), {
                    "job_id": body.job_id,
                    "summary": json.dumps(
                        {"status": payload.status, "standalone": True},
                        ensure_ascii=False, separators=(",", ":"),
                    ),
                })
                await db.commit()
                return {"status": payload.status, "standalone": True}
        payload = body.result
        status = payload.status
        entry = payload.entry if status == "ok" else None
        suppliers = payload.suppliers if status == "ok" else []
        if status == "ok":
            # 既有行刷新: 结构三件同样只补空(stale 刷新趟补历史欠账)
            await apply_structure_fill(
                db, chemical_id, resolve_structure(entry, payload.mol)
            )
        try:
            await upsert_externals(
                db, chemical_id=chemical_id, cas_number=cas_number,
                entry=entry, suppliers=suppliers, status=status,
            )
        except ValueError as exc:
            await db.execute(text("""
                UPDATE maintenance.cas_jobs
                SET status='failed',last_error_code='payload_invalid',
                    last_error_detail=:detail,
                    lease_owner=NULL,lease_token_hash=NULL,lease_expires_at=NULL,
                    heartbeat_at=NULL,updated_at=now(),completed_at=now()
                WHERE id=:job_id
            """), {"job_id": body.job_id, "detail": str(exc)[:2000]})
            await db.commit()
            raise HTTPException(422, str(exc)) from exc
        summary = {
            "chemical_id": chemical_id,
            "status": status,
            "supplier_count": len(suppliers),
            "entry_keys": sorted(entry.keys()) if entry else [],
        }
        await db.execute(text("""
            UPDATE maintenance.cas_jobs
            SET status='succeeded',result_summary=CAST(:summary AS jsonb),
                last_error_code=NULL,last_error_detail=NULL,
                lease_owner=NULL,lease_token_hash=NULL,lease_expires_at=NULL,
                heartbeat_at=NULL,updated_at=now(),completed_at=now()
            WHERE id=:job_id
        """), {
            "job_id": body.job_id,
            "summary": json.dumps(summary, ensure_ascii=False, separators=(",", ":")),
        })
        await db.commit()
        await cache_delete(CACHE_KEY.format(chemical_id=chemical_id))
        return summary
    except HTTPException:
        raise
    except Exception:
        await db.rollback()
        raise


@router.post("/cas/jobs/fail")
async def cas_fail_job(
    body: FailBody,
    db=Depends(get_db),
    worker: WorkerContext = Depends(authenticated_worker),
):
    try:
        job = await verified_cas_lease(db, body, worker.worker_id)
        retry = body.retryable and int(job[3]) < int(job[4])
        status = "retry" if retry else ("dead" if body.retryable else "failed")
        await db.execute(text("""
            UPDATE maintenance.cas_jobs
            SET status=:status,not_before=CASE WHEN :retry
                    THEN now()+make_interval(secs=>:retry_after) ELSE not_before END,
                last_error_code=:code,last_error_detail=:detail,
                lease_owner=NULL,lease_token_hash=NULL,lease_expires_at=NULL,
                heartbeat_at=NULL,updated_at=now(),
                completed_at=CASE WHEN :retry THEN NULL ELSE now() END
            WHERE id=:job_id
        """), {
            "status": status, "retry": retry, "retry_after": body.retry_after_seconds,
            "code": body.error_code, "detail": body.error_detail, "job_id": body.job_id,
        })
        await db.commit()
        return {"status": status}
    except Exception:
        await db.rollback()
        raise
