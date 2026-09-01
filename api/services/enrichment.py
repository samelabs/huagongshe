"""PubChem 详情回补服务层 — 自 api/enrichment.py 下沉, 逻辑零改动(批次3b)。"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy import text

from ..core.rate_limit import is_loopback_host


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

async def fetch_details(db: Any, chemical_id: int) -> dict[str, Any] | None:
    row = (await db.execute(text("""
        SELECT chemical_id,record_title,record_description,xlogp,
               topological_polar_surface_area,complexity,hbond_donor_count,
               hbond_acceptor_count,rotatable_bond_count,heavy_atom_count,
               formal_charge,computed_properties,physical_properties,
               ghs_cl...tion,hazards,safety_measures,toxicity,regulatory,
               pharmacology,uses_and_manufacturing,identifier_evidence,
               source_references,
               external_ids,ghs_codes,exp_props,exp_limits,reactivity,
               pubchem_created_on,pubchem_modified_on,
               fetched_at,updated_at
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
            "identifier_evidence", "source_references",
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
    chemical_id: int,
    cid: int,
    priority: int = 50,
    request_context: dict[str, Any] | None = None,
) -> int:
    """入列(0901 整记录化): cid 唯一键, dedupe=chemical_id 维度。
    error 行复活 = 同请求到达时整行接管翻态(UPDATE queued), 不并存。"""
    digest = hashlib.sha256(str(cid).encode("utf-8")).hexdigest()
    dedupe_key = f"cid:{chemical_id}:{digest}"
    row = (await db.execute(text("""
        INSERT INTO maintenance.pubchem_jobs
            (chemical_id,query_value,priority,dedupe_key,request_context)
        VALUES
            (:chemical_id,:query_value,:priority,:dedupe_key,
             CAST(:request_context AS jsonb))
        ON CONFLICT (dedupe_key) WHERE status IN ('queued','leased','error')
        DO UPDATE SET status=CASE WHEN maintenance.pubchem_jobs.status='error'
                              THEN 'queued' ELSE maintenance.pubchem_jobs.status END,
                      priority=greatest(maintenance.pubchem_jobs.priority,excluded.priority),
                      updated_at=now()
        RETURNING id
    """), {
        "chemical_id": chemical_id,
        "query_value": str(cid),
        "priority": priority,
        "dedupe_key": dedupe_key,
        "request_context": json.dumps(request_context or {}, ensure_ascii=False),
    })).fetchone()
    return int(row[0])


async def enqueue_chemical_if_needed(
    db: Any,
    chemical_id: int,
    *,
    sections: tuple[str, ...] = DEFAULT_SECTIONS,
    priority: int = 70,
    request: Request | None = None,
    actor: Any = None,
) -> tuple[dict[str, Any] | None, int | None, bool]:
    """pb_decide(0901 整记录化, 对齐 cb_decide 形态):
    无 cid=skip / 无行或 fetched_at 超 100 天窗=enqueue / 新鲜=serve_fresh。
    sections 参数保留签名兼容(路由层还在传), 判定不再使用。"""
    chemical = (await db.execute(text("""
        SELECT pubchem_cid FROM chemistry.chemicals WHERE id=:chemical_id
    """), {"chemical_id": chemical_id})).fetchone()
    if not chemical:
        raise HTTPException(404, "化合物不存在")
    details = await fetch_details(db, chemical_id)
    cid = chemical[0]
    if cid is None:
        # PB 仅 cid 维护(2026-08-29 收口): 无 cid 行不入队。
        return details, None, True
    # 判窗: fetched_at 一个字段(0901 定案)。100天=可完成周期, worker 扩容再收紧。
    fresh = False
    if details is not None:
        fetched_at = details.get("fetched_at")
        if fetched_at is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=100)
            value = fetched_at if fetched_at.tzinfo else fetched_at.replace(tzinfo=timezone.utc)
            fresh = value >= cutoff
    if fresh:
        return details, None, False
    # 入队是内部通道(T0)专属: SSR/agent 走 loopback 直连, 公网只读不触发。
    if request is not None and not is_loopback_host(request.client.host if request.client else None):
        return details, None, True
    job_id = await enqueue_job(
        db,
        chemical_id=chemical_id,
        cid=int(cid),
        priority=priority,
        request_context={"reason": "chemical_details"},
    )
    return details, job_id, True
