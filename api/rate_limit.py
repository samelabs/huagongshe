"""Small Redis-backed fixed-window limits for people and their API tokens."""

from __future__ import annotations

import hashlib
import ipaddress
import time

import redis.asyncio as redis
from fastapi import HTTPException, Request
from sqlalchemy import text

from .cache import pool
from .database import async_session


def is_loopback_host(host: str | None) -> bool:
    if not host:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


async def consume(bucket: str, identity: str, limit: int, window_seconds: int) -> tuple[int, int, bool]:
    window = int(time.time()) // window_seconds
    key = f"rate:{bucket}:{identity}:{window}"
    client = redis.Redis(connection_pool=pool)
    async with client.pipeline(transaction=True) as pipeline:
        pipeline.incr(key)
        pipeline.expire(key, window_seconds + 2)
        count, _ = await pipeline.execute()
    reset = (window + 1) * window_seconds
    count = int(count)
    return max(limit - count, 0), reset, count <= limit


async def enforce(bucket: str, identity: str, limit: int, window_seconds: int) -> None:
    try:
        remaining, reset, allowed = await consume(bucket, identity, limit, window_seconds)
    except Exception as exc:
        raise HTTPException(503, "限速服务暂时不可用，请稍后重试") from exc
    if not allowed:
        retry_after = max(reset - int(time.time()), 1)
        raise HTTPException(
            429,
            "请求过于频繁，请稍后重试",
            headers={"Retry-After": str(retry_after), "X-RateLimit-Remaining": "0"},
        )


async def _bearer_token_owner(token: str) -> int | None:
    """Return the user id owning a live API token, or None for anything else."""
    if len(token) < 32:
        return None
    digest = hashlib.sha256(token.encode()).digest()
    try:
        async with async_session() as db:
            return (await db.execute(text("""
                SELECT u.id
                FROM community.user_api_tokens t
                JOIN community.users u ON u.id=t.user_id
                WHERE t.token_hash=:digest AND t.revoked_at IS NULL
                  AND (t.expires_at IS NULL OR t.expires_at>now()) AND u.status='active'
            """), {"digest": digest})).scalar()
    except Exception:
        # Identity lookup is best-effort: a DB hiccup must not fail the request
        # here — the endpoint's own queries surface real outages.
        return None


async def request_identity(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        owner = await _bearer_token_owner(authorization[7:].strip())
        # Only verified tokens get their own per-person budget; forged or
        # unknown strings fall through to the address budget so rotating
        # headers cannot mint fresh limits.
        if owner is not None:
            return hashlib.sha256(f"api-token:{owner}".encode()).hexdigest()[:24]
    # Browser and anonymous traffic are keyed by address: arbitrary Cookie
    # headers must not create new budgets.
    raw = request.client.host if request.client else "unknown"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]
