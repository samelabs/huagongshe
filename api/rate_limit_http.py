"""Rate-limit → HTTP transport bridge (G2.R).

中性限流核心(api/core/rate_limit.py)不再产生 HTTPException; HTTP adapter
统一经本桥映射。本模块是 transport bridge, 不是第二 limiter engine ——
底层仍唯一调用 neutral core 的 enforce/structure_enter。

契约逐字保持:
  RateLimited        → 429 + Retry-After + X-RateLimit-Remaining: 0
  LimiterUnavailable → 503(无新 header)
  ResourceBusy       → 429 + Retry-After: 5(旧 _over_limit 契约, 无 X-头)
"""

from __future__ import annotations

from fastapi import HTTPException

from .core import rate_limit
from .core.rate_limit import (
    LimiterUnavailable,
    RateLimited,
    RateLimitError,
    ResourceBusy,
    structure_enter as _neutral_structure_enter,
)


def to_http_exception(exc: RateLimitError) -> HTTPException:
    """neutral 限流异常 → HTTPException(逐字等价旧 core 行为)。"""
    if isinstance(exc, RateLimited):
        return HTTPException(
            429,
            exc.detail,
            headers={"Retry-After": str(exc.retry_after or 1),
                     "X-RateLimit-Remaining": "0"},
        )
    if isinstance(exc, ResourceBusy):
        return HTTPException(
            429,
            exc.detail,
            headers={"Retry-After": str(exc.retry_after if exc.retry_after is not None else 5)},
        )
    if isinstance(exc, LimiterUnavailable):
        return HTTPException(503, exc.detail)
    return HTTPException(503, exc.detail)


async def enforce_http(bucket: str, identity: str, limit: int, window_seconds: int) -> None:
    """neutral enforce + HTTP 映射(与旧 rate_limit.enforce 逐字等价)。"""
    try:
        await rate_limit.enforce(bucket, identity, limit, window_seconds)
    except RateLimitError as exc:
        raise to_http_exception(exc) from exc


async def structure_enter_http(actor_id: int | None, bucket: str = "structure-search") -> list[str]:
    """neutral structure gate + HTTP 映射(与旧 structure_enter 逐字等价)。"""
    try:
        return await _neutral_structure_enter(actor_id, bucket)
    except RateLimitError as exc:
        raise to_http_exception(exc) from exc
