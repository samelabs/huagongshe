"""Public, read-oriented access to sparse chemical enrichment state.

This router is mounted below ``/api``.  Chemical detail is a product use case
where read-driven refresh is allowed: routes explicitly pass
``allow_refresh=True`` as product policy — transport (loopback or not) is
never authorization evidence.  Remote workers use ``/workapi``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .core.database import get_db
from .core.security import Actor, public_or_actor
from .services.enrichment import (
    EnrichmentChemicalNotFoundError, enqueue_chemical_if_needed,
)

router = APIRouter(tags=["enrichment"])








@router.get("/chemicals/{chemical_id}/details")
async def chemical_details(
    chemical_id: int,
    actor: Actor | None = Depends(public_or_actor),
    db=Depends(get_db),
):
    try:
        details, job_id, needs_refresh = await enqueue_chemical_if_needed(
            db, chemical_id,
            priority=80 if actor is not None else 50,
            # H1: 详情 use case 允许读驱动回补(产品策略), 与 transport 无关。
            allow_refresh=True,
            actor=actor,
        )
    except EnrichmentChemicalNotFoundError as exc:
        raise HTTPException(404, "化合物不存在") from exc
    if job_id is not None:
        await db.commit()
    return {
        "chemical_id": chemical_id,
        "details": details,
        "enrichment": {
            "status": "queued" if job_id is not None else ("stale" if needs_refresh else "current"),
            "job_id": job_id,
        },
    }



