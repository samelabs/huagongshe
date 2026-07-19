"""Redis cache client."""
import json
import redis.asyncio as redis
from .config import settings

pool = redis.ConnectionPool.from_url(settings.redis_url, decode_responses=True)


async def get_cache():
    """FastAPI dependency: yields a Redis connection."""
    return redis.Redis(connection_pool=pool)


async def cache_get(key: str):
    """Get cached value by key. Returns None on miss."""
    client = redis.Redis(connection_pool=pool)
    data = await client.get(key)
    if data:
        return json.loads(data)
    return None


async def cache_set(key: str, value, ttl: int = 0):
    """Set cached value with TTL."""
    client = redis.Redis(connection_pool=pool)
    if hasattr(value, 'model_dump'):
        value = value.model_dump()
    await client.set(key, json.dumps(value, default=str), ex=ttl or settings.cache_ttl)


async def cache_delete(*keys: str):
    """Delete exact cache keys after a reviewed core-data mutation."""
    if not keys:
        return
    client = redis.Redis(connection_pool=pool)
    await client.delete(*keys)
