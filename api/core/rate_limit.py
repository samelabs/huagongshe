"""Small Redis-backed fixed-window limits for people and their API tokens."""

from __future__ import annotations

import ipaddress
import logging
import time
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

import redis.asyncio as redis
from fastapi import HTTPException

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





# ---- 结构检索资源闸门(0912) -------------------------------------------------
# 两层: ① fixed-window 限频 ② in-flight 租约(并发上限)。
# 依据生产事实: DB pool 5+5=10 连接 / similarity 冷查 ~5s / statement_timeout 8s /
# substructure 低选择性 motif 冷查可吃满 8s。全局并发 4 → 最坏 4 个昂贵结构查询
# 同时占连接, 至少 6 个连接留给普通请求; 超限立即 429, 不占着连接等到 503。
STRUCTURE_ACTOR_RATE_LIMIT = 6      # actor 6 次/分钟
STRUCTURE_GLOBAL_RATE_LIMIT = 30    # 全局 30 次/分钟
STRUCTURE_ACTOR_INFLIGHT = 2        # actor 并发 2
STRUCTURE_GLOBAL_INFLIGHT = 4       # 全局并发 4
LEASE_TTL_SECONDS = 30              # > statement_timeout(8s); 进程崩溃自动回收

_ACQUIRE_LEASE = """
local cur = tonumber(redis.call('GET', KEYS[1]) or '0')
if cur >= tonumber(ARGV[1]) then return {0, cur} end
local n = redis.call('INCR', KEYS[1])
redis.call('PEXPIRE', KEYS[1], ARGV[2])
return {1, n}
"""

_RELEASE_LEASE = """
local cur = tonumber(redis.call('GET', KEYS[1]) or '0')
if cur <= 1 then redis.call('DEL', KEYS[1]) return 0 end
return redis.call('DECR', KEYS[1])
"""


async def acquire_lease(bucket: str, identity: str, limit: int,
                        ttl_seconds: int = LEASE_TTL_SECONDS) -> bool:
    """原子获取 in-flight 租约(INCR + PEXPIRE 同一 Lua)。

    fail-closed(0912): Redis 异常时抛 503, 不放行 — 限流/记账服务故障不能
    同时撤掉昂贵结构查询的最后一道 DB 并发保护(宁可结构检索不可用, 也不能让
    1.24 亿行上的 GiST 扫描无上限涌进 5+5 连接池)。release 侧相反: 异常只记
    日志, 靠 TTL 自愈(进程崩溃同理)。
    """
    key = f"lease:{bucket}:{identity}"
    client = redis.Redis(connection_pool=pool)
    try:
        ok, _ = await client.eval(_ACQUIRE_LEASE, 1, key, limit, ttl_seconds * 1000)
    except Exception as exc:
        logger.warning("lease acquire failed — fail-closed 503", exc_info=True,
                       extra={"lease_key": key})
        raise HTTPException(503, "结构检索限流服务暂时不可用，请稍后重试") from exc
    return bool(int(ok))


async def release_lease(bucket: str, identity: str) -> None:
    """释放租约(查询结束 finally 必调)。失败只记日志 — TTL 会自愈。"""
    key = f"lease:{bucket}:{identity}"
    client = redis.Redis(connection_pool=pool)
    try:
        await client.eval(_RELEASE_LEASE, 1, key)
    except Exception:
        logger.warning("lease release failed — TTL will reclaim", exc_info=True,
                       extra={"lease_key": key})


def _over_limit() -> HTTPException:
    return HTTPException(
        429, "结构检索并发已达上限，请稍后重试",
        headers={"Retry-After": "5", "X-RateLimit-Remaining": "0"},
    )


async def structure_enter(actor_id: int | None, bucket: str = "structure-search") -> list[str]:
    """进入结构检索闸门: 限频(第一层) → 获取 in-flight 租约(第二层)。

    返回已持有的租约身份列表(交给 structure_exit 释放)。超限抛 429。
    调用方必须已查过缓存 — cache hit 不进这里, 不占限流也不占租约。
    """
    identity = f"actor:{actor_id}" if actor_id is not None else None
    # fixed-window 行为不变: enforce 限流服务异常 → 503(原口径), 超限 → 429。
    if identity is not None:
        await enforce(bucket, identity, STRUCTURE_ACTOR_RATE_LIMIT, 60)
    await enforce(bucket, "global", STRUCTURE_GLOBAL_RATE_LIMIT, 60)

    held: list[str] = []
    if identity is not None:
        if await acquire_lease(bucket, identity, STRUCTURE_ACTOR_INFLIGHT):
            held.append(identity)
        else:
            raise _over_limit()
    if await acquire_lease(bucket, "global", STRUCTURE_GLOBAL_INFLIGHT):
        held.append("global")
    else:
        await structure_exit(held, bucket)
        raise _over_limit()
    return held


async def structure_exit(held: list[str] | None, bucket: str = "structure-search") -> None:
    """释放租约(finally 调用)。异常吞掉, 不影响响应。"""
    for identity in held or []:
        await release_lease(bucket, identity)


@asynccontextmanager
async def structure_slot(actor_id: int | None, bucket: str = "structure-search"):
    """with 形式的闸门: async with structure_slot(actor.id) as _: ..."""
    held = await structure_enter(actor_id, bucket)
    try:
        yield held
    finally:
        await structure_exit(held, bucket)
