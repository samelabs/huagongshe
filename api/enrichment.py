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

from .core.database import get_db
from .core.rate_limit import is_loopback_host
from .core.security import internal_or_actor
from .services.enrichment import (
    ALLOWED_SECTIONS, DEFAULT_SECTIONS, DISPLAY_EVIDENCE_SECTIONS,
    DISPLAY_ENTRY_LIMIT, DISPLAY_VALUE_LIMIT,
    normalize_sections, fetch_details, display_details, enqueue_job, enqueue_chemical_if_needed,
)

router = APIRouter(tags=["enrichment"])








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
