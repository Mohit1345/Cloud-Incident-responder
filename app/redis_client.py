"""
redis_client.py — aioredis connection pool + cache helpers.
Hit/miss counters are stored in Redis itself so /metrics can report
them without any in-process state.
"""

import json
import logging
from typing import Any

import redis.asyncio as aioredis
from app.config import settings

logger = logging.getLogger(__name__)

_redis: aioredis.Redis | None = None

COUNTER_HITS   = "stats:cache_hits"
COUNTER_MISSES = "stats:cache_misses"


async def init_redis() -> None:
    global _redis
    logger.info("Connecting to Redis: %s", settings.REDIS_URL)
    _redis = aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
        max_connections=200,
    )
    await _redis.ping()
    logger.info("Redis ready.")


async def close_redis() -> None:
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None


def get_redis() -> aioredis.Redis:
    if _redis is None:
        raise RuntimeError("Redis not initialised. Call init_redis() first.")
    return _redis


async def cache_get(key: str) -> Any | None:
    r = get_redis()
    raw = await r.get(key)
    if raw is not None:
        await r.incr(COUNTER_HITS)
        logger.debug("Cache HIT  key=%s", key)
        return json.loads(raw)
    await r.incr(COUNTER_MISSES)
    logger.debug("Cache MISS key=%s", key)
    return None


async def cache_set(key: str, value: Any, ttl: int | None = None) -> None:
    r = get_redis()
    ttl = ttl if ttl is not None else settings.CACHE_TTL_SECONDS
    await r.set(key, json.dumps(value), ex=ttl)
    logger.debug("Cache SET  key=%s  ttl=%ds", key, ttl)


async def cache_delete(key: str) -> int:
    r = get_redis()
    deleted = await r.delete(key)
    logger.info("Cache DEL  key=%s  deleted=%d", key, deleted)
    return deleted


async def get_cache_stats() -> dict:
    r = get_redis()
    hits   = int(await r.get(COUNTER_HITS)   or 0)
    misses = int(await r.get(COUNTER_MISSES) or 0)
    total  = hits + misses
    hit_rate = round(hits / total * 100, 2) if total > 0 else 0.0

    info = await r.info("stats")
    return {
        "cache_hits":              hits,
        "cache_misses":            misses,
        "cache_total":             total,
        "hit_rate_pct":            hit_rate,
        "redis_ops_per_sec":       info.get("instantaneous_ops_per_sec", 0),
        "redis_connected_clients": (await r.info("clients")).get("connected_clients", 0),
    }


async def reset_cache_stats() -> None:
    r = get_redis()
    await r.delete(COUNTER_HITS, COUNTER_MISSES)