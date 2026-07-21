"""Small Redis-backed fixed-window limits for people and their Agent tokens."""

from __future__ import annotations

import hashlib
import ipaddress
import time

import redis.asyncio as redis
from fastapi import HTTPException, Request

from .cache import pool


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


def request_identity(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    cookie = request.headers.get("cookie", "")
    raw = authorization if authorization.lower().startswith("bearer ") else cookie
    if not raw:
        raw = request.client.host if request.client else "unknown"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]
