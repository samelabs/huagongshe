"""Public, read-oriented access to sparse chemical enrichment state.

This router is mounted below ``/api``.  Cache-fill jobs are enqueued only for
loopback (internal) requests; public reads never trigger processing.  Remote
workers use ``/workapi``.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text

from .database import get_db
from .rate_limit import is_loopback_host
from .security import internal_or_actor

router = APIRouter(tags=["enrichment"])

ALLOWED_SECTIONS = frozenset(
    {
        "computed",
        "identifiers",
        "synonyms",
        "physical",
        "safety",
        "toxicity",
        "regulatory",
        "pharmacology",
        "uses",
    }
)
DEFAULT_SECTIONS = ("computed", "identifiers", "synonyms")
DISPLAY_EVIDENCE_SECTIONS = (
    "physical_properties", "ghs_classification", "hazards", "safety_measures",
    "toxicity", "regulatory", "pharmacology", "uses_and_manufacturing",
)
DISPLAY_ENTRY_LIMIT = 12
DISPLAY_VALUE_LIMIT = 6


def normalize_sections(raw: str | list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    if raw is None:
        return DEFAULT_SECTIONS
    values = raw.split(",") if isinstance(raw, str) else raw
    sections = tuple(sorted({value.strip().lower() for value in values if value.strip()}))
    if not sections or any(value not in ALLOWED_SECTIONS for value in sections):
        raise HTTPException(400, "不支持的补全信息分区")
    return sections


def details_dict(row: Any | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row._mapping if hasattr(row, "_mapping") else row)


async def fetch_details(db: Any, chemical_id: int) -> dict[str, Any] | None:
    row = (await db.execute(text("""
        SELECT chemical_id,record_title,record_description,xlogp,
               topological_polar_surface_area,complexity,hbond_donor_count,
               hbond_acceptor_count,rotatable_bond_count,heavy_atom_count,
               formal_charge,computed_properties,physical_properties,
               ghs_classification,hazards,safety_measures,toxicity,regulatory,
               pharmacology,uses_and_manufacturing,identifier_evidence,
               source_references,fetched_sections,section_fetched_at,
               section_source_hashes,
               pubchem_created_on,pubchem_modified_on,schema_version,
               fetched_at,expires_at,updated_at
        FROM chemistry.chemical_pubchem WHERE chemical_id=:chemical_id
    """), {"chemical_id": chemical_id})).mappings().fetchone()
    return dict(row) if row else None


def display_details(details: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return the bounded page projection without changing stored evidence."""
    if details is None:
        return None
    result = {
        key: value for key, value in details.items()
        if key not in {
            "identifier_evidence", "source_references", "section_source_hashes",
            "computed_properties",
        }
    }
    for section in DISPLAY_EVIDENCE_SECTIONS:
        block = result.get(section)
        if not isinstance(block, dict):
            continue
        source = block.get("entries")
        if not isinstance(source, dict):
            source = block
        entries: dict[str, Any] = {}
        for key, values in list(source.items())[:DISPLAY_ENTRY_LIMIT]:
            entries[key] = values[:DISPLAY_VALUE_LIMIT] if isinstance(values, list) else values
        result[section] = {"entries": entries}
    return result


async def enqueue_job(
    db: Any,
    *,
    chemical_id: int | None,
    query_kind: str,
    query_value: str,
    sections: tuple[str, ...] = DEFAULT_SECTIONS,
    priority: int = 50,
    request_context: dict[str, Any] | None = None,
) -> int:
    normalized_value = query_value.strip()
    digest = hashlib.sha256(normalized_value.encode("utf-8")).hexdigest()
    dedupe_key = f"{query_kind}:{chemical_id or '-'}:{digest}:{','.join(sections)}"
    row = (await db.execute(text("""
        INSERT INTO maintenance.pubchem_jobs
            (chemical_id,query_kind,query_value,sections,priority,dedupe_key,request_context)
        VALUES
            (:chemical_id,:query_kind,:query_value,:sections,:priority,:dedupe_key,
             CAST(:request_context AS jsonb))
        ON CONFLICT (dedupe_key) WHERE status IN ('queued','leased','retry')
        DO UPDATE SET priority=greatest(maintenance.pubchem_jobs.priority,excluded.priority),
                      updated_at=now()
        RETURNING id
    """), {
        "chemical_id": chemical_id,
        "query_kind": query_kind,
        "query_value": normalized_value,
        "sections": list(sections),
        "priority": priority,
        "dedupe_key": dedupe_key,
        "request_context": json.dumps(request_context or {}, ensure_ascii=False),
    })).fetchone()
    job_id = int(row[0])
    await db.execute(text("""
        INSERT INTO maintenance.pubchem_job_events(job_id,event_type,details)
        SELECT :job_id,'queued','{}'::jsonb
        WHERE NOT EXISTS (
            SELECT 1 FROM maintenance.pubchem_job_events
            WHERE job_id=:job_id AND event_type='queued'
        )
    """), {"job_id": job_id})
    return job_id


async def enqueue_chemical_if_needed(
    db: Any,
    chemical_id: int,
    *,
    sections: tuple[str, ...] = DEFAULT_SECTIONS,
    priority: int = 70,
    request: Request | None = None,
    actor: Any = None,
) -> tuple[dict[str, Any] | None, int | None, bool]:
    chemical = (await db.execute(text("""
        SELECT pubchem_cid,smiles,inchikey FROM chemistry.chemicals WHERE id=:chemical_id
    """), {"chemical_id": chemical_id})).fetchone()
    if not chemical:
        raise HTTPException(404, "化合物不存在")
    details = await fetch_details(db, chemical_id)
    section_times = (details or {}).get("section_fetched_at") or {}
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    def is_fresh(section: str) -> bool:
        raw = section_times.get(section)
        if not isinstance(raw, str):
            return False
        try:
            value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return False
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value >= cutoff

    needed = tuple(section for section in sections if not is_fresh(section))
    if not needed:
        return details, None, False
    # 入队是内部通道(T0)专属: SSR/agent 走 loopback 直连, 公网请求只读不触发处理.
    # 队列去重(dedupe_key)+worker 速率控制是容量上界, 内部流量无需 API 层限流.
    if request is not None and not is_loopback_host(request.client.host if request.client else None):
        return details, None, True
    # 水位闸门(2026-08-27): 匿名 SSR(爬虫翻页)可在一天内灌 5 万+ 任务.
    # 活跃积压超阈值时, 无 actor 的入队直接降级不入队(返回 stale);
    # 有 actor 的用户请求不受限. 阈值=2万(worker 4rps 约 1.5 天存量上限).
    if actor is None:
        active = (await db.execute(text("""
            SELECT count(*) FROM maintenance.pubchem_jobs
            WHERE status IN ('queued','retry')
        """))).scalar() or 0
        if active >= 20000:
            return details, None, True
    if chemical[0] is not None:
        query_kind, query_value = "cid", str(chemical[0])
    else:
        # PB 仅 cid 拉取(2026-08-29 收口): PB 定位=cid 库维护者, 非发现通道。
        # 无 cid 行(PB 未收录结构: ORD 裸行/CB 占位/SMILES 建行)不入队 —
        # inchikey 兜底询问(0a76f43)对这批结构必然 not_found, 只产 miss 噪音
        # 与 governor 跳闸。结构三件本地 RDKit 已算齐, 化合物页不缺数据。
        return details, None, True
    job_id = await enqueue_job(
        db,
        chemical_id=chemical_id,
        query_kind=query_kind,
        query_value=query_value,
        sections=needed,
        priority=priority,
        request_context={"reason": "chemical_details"},
    )
    return details, job_id, True


@router.get("/chemicals/{chemical_id}/details")
async def chemical_details(
    request: Request,
    chemical_id: int,
    sections: str = Query("computed,identifiers", max_length=200),
    actor: Actor | None = Depends(internal_or_actor),
    db=Depends(get_db),
):
    requested = normalize_sections(sections)
    details, job_id, needs_refresh = await enqueue_chemical_if_needed(
        db, chemical_id, sections=requested,
        priority=80 if actor is not None else 50, request=request, actor=actor,
    )
    if job_id is not None:
        await db.commit()
    return {
        "chemical_id": chemical_id,
        "details": details,
        "enrichment": {
            "status": "queued" if job_id is not None else ("stale" if needs_refresh else "current"),
            "job_id": job_id,
            "requested_sections": list(requested),
        },
    }


@router.get("/enrichment/jobs/{job_id}")
async def enrichment_job(
    job_id: int,
    actor: Actor | None = Depends(internal_or_actor),
    db=Depends(get_db),
):
    row = (await db.execute(text("""
        SELECT id,chemical_id,status,sections,resolved_pubchem_cid,result_summary,
               created_at,updated_at,completed_at
        FROM maintenance.pubchem_jobs WHERE id=:job_id
    """), {"job_id": job_id})).mappings().fetchone()
    if not row:
        raise HTTPException(404, "补全任务不存在")
    return dict(row)
