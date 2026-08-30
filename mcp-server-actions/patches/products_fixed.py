"""
products.py — Core business logic.

FIXED VERSION — applied by the incident-responder-actions MCP server's
apply_lock_fix tool, only after a human has approved the remediation.

get_product() now takes a short-lived Redis lock (SET NX EX) before going
to Postgres on a cache miss. The first request to miss wins the lock and
repopulates the cache; every concurrent request behind it waits briefly and
re-reads the cache instead of also hitting the database. This is what stops
the stampede: N concurrent misses collapse into 1 DB query instead of N.
"""

import asyncio
import logging
import time
from typing import Any

from app.config import settings
from app.database import fetch_product
from app.redis_client import cache_get, cache_set, get_redis

logger = logging.getLogger(__name__)

LOCK_TTL_SECONDS = 5
LOCK_WAIT_RETRIES = 20
LOCK_WAIT_INTERVAL_SECONDS = 0.1


async def get_product(product_id: int) -> dict | None:
    """
    Cache-aside lookup with a distributed lock on cache miss.

    Request A → Redis MISS → acquires lock → fetches from Postgres → fills cache → releases lock
    Request B → Redis MISS → lock held      → waits, re-reads cache → gets A's result
    Request C → Redis MISS → lock held      → waits, re-reads cache → gets A's result
    """
    cache_key = f"product:{product_id}"
    lock_key = f"lock:product:{product_id}"

    t0 = time.monotonic()
    cached = await cache_get(cache_key)
    redis_latency_ms = (time.monotonic() - t0) * 1000

    if cached is not None:
        logger.debug("product=%d  source=redis  latency=%.1fms", product_id, redis_latency_ms)
        return cached

    logger.warning("CACHE MISS  product=%d  redis_latency=%.1fms", product_id, redis_latency_ms)

    r = get_redis()
    got_lock = await r.set(lock_key, "1", nx=True, ex=LOCK_TTL_SECONDS)

    if not got_lock:
        # Someone else is already fetching — wait briefly and re-check the cache
        # instead of also hitting Postgres.
        for _ in range(LOCK_WAIT_RETRIES):
            await asyncio.sleep(LOCK_WAIT_INTERVAL_SECONDS)
            cached = await cache_get(cache_key)
            if cached is not None:
                logger.debug("product=%d  source=redis(after-wait)", product_id)
                return cached
        logger.warning(
            "product=%d  lock wait timed out after %.1fs, falling back to direct DB fetch",
            product_id, LOCK_WAIT_RETRIES * LOCK_WAIT_INTERVAL_SECONDS,
        )

    try:
        t1 = time.monotonic()
        try:
            product = await fetch_product(product_id)
        except Exception as exc:
            logger.error("DB ERROR  product=%d  error=%s", product_id, exc)
            raise
        db_latency_ms = (time.monotonic() - t1) * 1000
        logger.info("DB HIT  product=%d  db_latency=%.1fms", product_id, db_latency_ms)

        if product is None:
            return None

        await cache_set(cache_key, product, ttl=settings.CACHE_TTL_SECONDS)
        return product
    finally:
        if got_lock:
            await r.delete(lock_key)


class CheckoutError(Exception):
    pass


async def checkout(product_id: int, quantity: int = 1) -> dict[str, Any]:
    """
    Simulate checkout. Times out during stampede -> HTTP 504.
    (Unchanged from the original — included so the file is drop-in complete.)

    Flow: get product -> validate stock -> create order (stub)
    """
    try:
        product = await asyncio.wait_for(
            get_product(product_id),
            timeout=settings.CHECKOUT_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.error(
            "CHECKOUT TIMEOUT  product=%d  timeout=%.1fs",
            product_id,
            settings.CHECKOUT_TIMEOUT_SECONDS,
        )
        raise CheckoutError(
            f"Checkout timed out after {settings.CHECKOUT_TIMEOUT_SECONDS}s "
            f"(product {product_id} fetch too slow — likely DB saturation)"
        )

    if product is None:
        raise CheckoutError(f"Product {product_id} not found")

    if product.get("stock", 0) < quantity:
        raise CheckoutError(
            f"Insufficient stock: requested={quantity} available={product.get('stock', 0)}"
        )

    return {
        "order_id":   f"ORD-{product_id}-{int(time.time() * 1000)}",
        "product_id": product_id,
        "quantity":   quantity,
        "unit_price": product.get("sale_price") or product.get("price"),
        "status":     "confirmed",
    }
