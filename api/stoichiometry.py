"""Reaction stoichiometry calculator — HTTP adapter (G2.1).

业务计算在 api/services/stoichiometry.py(transport-neutral, 唯一一份);
本文件只保留: HTTP DTO 装配、dependency、限流编排(entrypoint policy)、
HTTP 错误映射。行为(URL/auth/status/detail/响应)与基线逐字一致。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .core.config import settings
from .core.rate_limit import enforce
from .core.security import Actor, public_or_actor
from .schemas.stoichiometry import ScaleInput
from .services import stoichiometry as stoich_service

router = APIRouter(tags=["stoichiometry"])


@router.post("/stoichiometry/scale", operation_id="calculate_stoichiometry")
async def calculate_stoichiometry(
    body: ScaleInput,
    actor: Actor | None = Depends(public_or_actor),
) -> dict:
    """Scale a batch from a chosen basis component to a full role-based dosing table."""
    identity = f"u{actor.id}" if actor else "anon"
    await enforce("stoich", identity, settings.api_stoich_limit_per_minute, 60)

    try:
        return await stoich_service.compute(body)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
