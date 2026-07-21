"""Redis cache client.

Cache failures must never change the result of a database read or mutation.
Rate limiting deliberately uses its own fail-closed path in ``rate_limit``.
"""
import json
import logging
import redis.asyncio as redis
from .config import settings

logger = logging.getLogger(__name__)
pool = redis.ConnectionPool.from_url(settings.redis_url, decode_responses=True)


async def get_cache():
    """FastAPI dependency: yields a Redis connection."""
    return redis.Redis(connection_pool=pool)


async def cache_get(key: str):
    """Get cached value by key. Returns None on miss."""
    client = redis.Redis(connection_pool=pool)
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
    client = redis.Redis(connection_pool=pool)
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
    client = redis.Redis(connection_pool=pool)
    try:
        await client.delete(*keys)
    except Exception:
        logger.warning("cache delete failed", exc_info=True, extra={"cache_keys": keys})
