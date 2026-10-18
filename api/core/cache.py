"""Redis cache client.

Cache failures must never change the result of a database read or mutation.
Rate limiting deliberately uses its own fail-closed path in ``rate_limit``.
"""
import asyncio
import json
import logging
import weakref

import redis.asyncio as redis
from .config import settings

logger = logging.getLogger(__name__)
pool = redis.ConnectionPool.from_url(settings.redis_url, decode_responses=True)

# 按事件循环隔离的池: redis asyncio 连接
# 绑定创建它的 loop, 测试常见 asyncio.run-per-call 模式下每次调用都是新 loop,
# 复用旧 loop 的连接必然报错(cache 层吞掉变降级, 限流层 fail-closed 变 503)。
# 生产单事件循环(uvicorn/uvloop)下 get_running_loop 恒同一对象 → 行为与
# 单一模块级 pool 完全一致, 零额外成本。
_loop_pools: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, redis.ConnectionPool]" = weakref.WeakKeyDictionary()


def current_pool() -> redis.ConnectionPool:
    """当前事件循环的连接池(生产=单循环复用; 测试=每循环独立)。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # 无运行循环(同步上下文) — 沿用模块级池
        return pool
    p = _loop_pools.get(loop)
    if p is None:
        p = redis.ConnectionPool.from_url(settings.redis_url, decode_responses=True)
        _loop_pools[loop] = p
    return p


async def get_cache():
    """FastAPI dependency: yields a Redis connection."""
    return redis.Redis(connection_pool=current_pool())


async def cache_get(key: str):
    """Get cached value by key. Returns None on miss."""
    client = redis.Redis(connection_pool=current_pool())
    try:
        data = await client.get(key)
    except Exception:
        logger.warning("cache read failed", exc_info=True, extra={"cache_key": key})
        return None
    if data:
        try:
            return json.loads(data)
        except (TypeError, ValueError):
            logger.warning("invalid cached JSON", extra={"cache_key": key})
    return None


async def cache_set(key: str, value, ttl: int = 0):
    """Set cached value with TTL."""
    client = redis.Redis(connection_pool=current_pool())
    if hasattr(value, 'model_dump'):
        value = value.model_dump()
    try:
        await client.set(key, json.dumps(value, default=str), ex=ttl or settings.cache_ttl)
    except Exception:
        logger.warning("cache write failed", exc_info=True, extra={"cache_key": key})


async def cache_delete(*keys: str):
    """Delete exact cache keys after a reviewed core-data mutation."""
    if not keys:
        return
    client = redis.Redis(connection_pool=current_pool())
    try:
        await client.delete(*keys)
    except Exception:
        logger.warning("cache delete failed", exc_info=True, extra={"cache_keys": keys})
