"""Reaction stoichiometry calculator — HTTP adapter.

业务计算在 api/services/stoichiometry.py(transport-neutral, 唯一一份);
本文件只保留: HTTP DTO 装配、dependency、限流编排(entrypoint policy)、
HTTP 错误映射。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from .core.config import settings
from .core.rate_limit import client_ip
from .rate_limit_http import enforce_http
from .core.security import Actor, public_or_actor
from .schemas.stoichiometry import ScaleInput
from .services import stoichiometry as stoich_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["stoichiometry"])


@router.post("/stoichiometry/scale", operation_id="calculate_stoichiometry")
async def calculate_stoichiometry(
    body: ScaleInput,
    request: Request,
    actor: Actor | None = Depends(public_or_actor),
) -> dict:
    """Scale a batch from a chosen basis component to a full role-based dosing table."""
    # 登录按用户分桶; 匿名按来源 IP 分桶, 拿不到来源 IP 时不设限流并记警。
    if actor:
        await enforce_http("stoich", f"u{actor.id}", settings.api_stoich_limit_per_minute, 60)
    else:
        ip = client_ip(request.headers)
        if ip:
            await enforce_http("stoich", f"ip:{ip}", settings.api_stoich_limit_per_minute, 60)
        else:
            logger.warning(
                "stoichiometry without client IP (no x-real-ip): "
                "anonymous rate limit skipped")

    try:
        return await stoich_service.compute(body)
    except ValueError as exc:
        raise HTTPException(400, {"message": str(exc), "kind": "invalid_input"}) from exc
