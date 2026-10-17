"""Small Redis-backed fixed-window limits for people and their API tokens.

.R(): transport-neutral 化 —— 本文件不再产生
transport-specific exception, 改抛 neutral 语义异常(RateLimited / LimiterUnavailable /
ResourceBusy)。HTTP status/header 由 HTTP transport bridge
(api/rate_limit_http.py)映射; MCP adapter 自行映射 ToolError。

单一 limiter engine: consume 的 fixed-window INCR/EXPIRE 与 Lua lease
实现自始未变, 本轮只改异常语义层。
"""

from __future__ import annotations

import ipaddress
import logging
import time
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

import redis.asyncio as redis

from . import cache as _cache


# ---------------------------------------------------------------------------
# neutral 语义异常(.R): 只携带 detail + retry_after, 不含 HTTP status/header。
# ---------------------------------------------------------------------------

class RateLimitError(Exception):
    """中性基类: 限流体系内可预期的失败(便于调用方统一捕获)。"""

    detail: str
    retry_after: int | None

    def __init__(self, detail: str, retry_after: int | None = None):
        super().__init__(detail)
        self.detail = detail
        self.retry_after = retry_after


class RateLimited(RateLimitError):
    """固定窗口超限(原 HTTP 429 + Retry-After 路径)。"""


class LimiterUnavailable(RateLimitError):
    """限流基础设施不可用(Redis 故障 fail-closed, 原 HTTP 503 路径)。"""


class ResourceBusy(RateLimitError):
    """in-flight 资源饱和(原结构闸门 429 Retry-After:5 路径)。"""


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
    client = redis.Redis(connection_pool=_cache.current_pool())
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
        raise LimiterUnavailable("限速服务暂时不可用，请稍后重试") from exc
    if not allowed:
        retry_after = max(reset - int(time.time()), 1)
        raise RateLimited("请求过于频繁，请稍后重试", retry_after=retry_after)


async def check(bucket: str, identity: str, limit: int, window_seconds: int) -> bool:
    """只读探测: 桶当前是否仍允许一次计数。不递增计数器、不可用时报允许。

    用途: "失败后计数"的桶在动作发生前预检 —— 已满直接拒绝, 不再发起
    外部请求; 探测本身失败时按未满放行, 不让预检变成新的故障点。
    """
    window = int(time.time()) // window_seconds
    key = f"rate:{bucket}:{identity}:{window}"
    client = redis.Redis(connection_pool=_cache.current_pool())
    try:
        count = int(await client.get(key) or 0)
    except Exception:
        return True
    return count <= limit


def client_ip(headers) -> str | None:
    """按 IP 限流的统一分桶键: 读 nginx 覆盖写入的 X-Real-IP。

    生产链路 Cloudflare → nginx(cloudflare-realip) → FastAPI: nginx 把
    $remote_addr(真实访客 IP)写入 X-Real-IP, 客户端无法伪造。X-Forwarded-For
    首段是请求自带的值(Cloudflare 原样保留再追加), 可伪造, 不用于分桶。
    接受任何带 .get() 的 headers 映射(FastAPI Request.headers 与 MCP
    ctx.headers 通用)。头缺失/为空返回 None —— 调用方按"拿不到 IP 不落
    全站共用桶"处理, 避免所有匿名请求挤进同一个桶。
    """
    if not headers:
        return None
    value = headers.get("x-real-ip") or headers.get("X-Real-Ip")
    if value:
        return value.strip() or None
    return None





# ---- 结构检索资源闸门 -------------------------------------------------------
# 两层: ① 按身份 fixed-window 限频 ② in-flight 租约(并发上限)。
# 依据生产事实: DB pool 5+5=10 连接 / similarity 冷查 ~5s / statement_timeout 8s /
# substructure 低选择性 motif 冷查可吃满 8s。全局并发 4 → 最坏 4 个昂贵结构查询
# 同时占连接, 至少 6 个连接留给普通请求; 超限立即拒绝, 不占着连接等 503。
STRUCTURE_ACTOR_RATE_LIMIT = 6      # 单一用户 6 次/分钟
STRUCTURE_ACTOR_INFLIGHT = 2        # 单一用户并发 2
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

    fail-closed(): Redis 异常时抛 LimiterUnavailable, 不放行 —
    限流/记账服务故障不能同时撤掉昂贵结构查询的最后一道 DB 并发保护
    (宁可结构检索不可用, 也不能让 1.24 亿行上的 GiST 扫描无上限涌进
    5+5 连接池)。release 侧相反: 异常只记日志, 靠 TTL 自愈(进程崩溃同理)。
    busy(已满)仍返回 False, 不抛异常。
    """
    key = f"lease:{bucket}:{identity}"
    client = redis.Redis(connection_pool=_cache.current_pool())
    try:
        ok, _ = await client.eval(_ACQUIRE_LEASE, 1, key, limit, ttl_seconds * 1000)
    except Exception as exc:
        logger.warning("lease acquire failed — fail-closed unavailable", exc_info=True,
                       extra={"lease_key": key})
        raise LimiterUnavailable("结构检索限流服务暂时不可用，请稍后重试") from exc
    return bool(int(ok))


async def release_lease(bucket: str, identity: str) -> None:
    """释放租约(查询结束 finally 必调)。失败只记日志 — TTL 会自愈。"""
    key = f"lease:{bucket}:{identity}"
    client = redis.Redis(connection_pool=_cache.current_pool())
    try:
        await client.eval(_RELEASE_LEASE, 1, key)
    except Exception:
        logger.warning("lease release failed — TTL will reclaim", exc_info=True,
                       extra={"lease_key": key})


def _over_limit() -> ResourceBusy:
    # 旧 _over_limit() HTTP 契约: 429 + Retry-After:5(原值保留, 由 HTTP bridge 重建)。
    return ResourceBusy(
        "结构检索并发已达上限，请稍后重试",
        retry_after=5,
    )


async def structure_enter(actor_id: int | None, bucket: str = "structure-search") -> list[str]:
    """进入结构检索闸门: 限频(第一层) → 获取 in-flight 租约(第二层)。

    返回已持有的租约身份列表(交给 structure_exit 释放)。超限抛
    RateLimited / ResourceBusy / LimiterUnavailable(neutral)。
    调用方必须已查过缓存 — cache hit 不进这里, 不占限流也不占租约。
    """
    identity = f"actor:{actor_id}" if actor_id is not None else None
    # fixed-window 行为不变: enforce 限流服务异常 → LimiterUnavailable, 超限 → RateLimited。
    # 限频只按身份设桶(全站共享速率桶不设在业务代码里, 全站容量保护交给接入层)。
    if identity is not None:
        await enforce(bucket, identity, STRUCTURE_ACTOR_RATE_LIMIT, 60)

    held: list[str] = []
    if identity is not None:
        if await acquire_lease(bucket, identity, STRUCTURE_ACTOR_INFLIGHT):
            held.append(identity)
        else:
            raise _over_limit()
    try:
        granted = await acquire_lease(bucket, "global", STRUCTURE_GLOBAL_INFLIGHT)
    except RateLimitError:
        # global 侧 Redis 故障(fail-closed): 已持有的 actor 租约必须立刻释放,
        # 不能等 TTL(30s) — 否则单个 actor 的槽位被故障窗口白白锁住。
        await structure_exit(held, bucket)
        raise
    if granted:
        held.append("global")
    else:
        await structure_exit(held, bucket)
        raise _over_limit()
    return held


async def release_leases(held: list[str] | None, bucket: str) -> None:
    """按身份列表释放租约(任意 bucket)。异常吞掉, 不影响响应。"""
    for identity in held or []:
        await release_lease(bucket, identity)


async def structure_exit(held: list[str] | None, bucket: str = "structure-search") -> None:
    """释放租约(finally 调用)。异常吞掉, 不影响响应。"""
    await release_leases(held, bucket)


@asynccontextmanager
async def structure_slot(actor_id: int | None, bucket: str = "structure-search"):
    """with 形式的闸门: async with structure_slot(actor.id) as _: ..."""
    held = await structure_enter(actor_id, bucket)
    try:
        yield held
    finally:
        await structure_exit(held, bucket)
