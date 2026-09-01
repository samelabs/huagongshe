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
    # 新鲜窗口30→100天(2026-08-30): 1.24亿行×全section, worker 4rps消化力下
    # 30天周期客观无法巡完一圈, 任务会永远积压。100天=可完成周期; worker
    # 扩容(外置上线)后再收紧。
    cutoff = datetime.now(timezone.utc) - timedelta(days=100)

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
    # 水位闸门拆除(2026-08-30): 当年防的是 inchikey 兜底必 miss 灌队列
    # (8/26-27 详情页访问灌 4290 个)。inchikey 通道已退役(9e8adbb),
    # PB 仅 cid 维护: 任务有 dedupe 去重且 cid 查询必命中不堆积,
    # 闸门只剩误伤 cid 维护入队一个作用, 拆。
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
