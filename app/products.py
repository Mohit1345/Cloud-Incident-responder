"""
products.py — Core business logic.

THE INTENTIONAL BUG IS HERE.

get_product() uses a plain cache-aside pattern with no distributed lock
and no request coalescing. When the cache entry for product:123 expires
while thousands of requests are in-flight, every single one will:

  1. Call redis.get("product:123")  → MISS
  2. Call postgres.fetchrow(...)    → slow (pg_sleep)
  3. Call redis.set("product:123")  → too late, stampede already happened
"""

import asyncio
import logging
import time
from typing import Any

from app.config import settings
from app.database import fetch_product
from app.redis_client import cache_get, cache_set

logger = logging.getLogger(__name__)


async def get_product(product_id: int) -> dict | None:
    """
    Cache-aside lookup — INTENTIONALLY VULNERABLE (no lock on cache miss).

    ┌─────────────────────────────────────────────────────────┐
    │  Request A → Redis MISS ─┐                              │
    │  Request B → Redis MISS ─┤                              │
    │  Request C → Redis MISS ─┼──► PostgreSQL (all of them) │
    │  Request D → Redis MISS ─┤                              │
    │  Request E → Redis MISS ─┘                              │
    └─────────────────────────────────────────────────────────┘
    """
    cache_key = f"product:{product_id}"

    # Step 1: Try Redis
    t0 = time.monotonic()
    cached = await cache_get(cache_key)
    redis_latency_ms = (time.monotonic() - t0) * 1000

    if cached is not None:
        logger.debug("product=%d  source=redis  latency=%.1fms", product_id, redis_latency_ms)
        return cached

    # Step 2: Cache MISS → hit PostgreSQL
    # NO LOCK HERE — this is the vulnerability
    logger.warning("CACHE MISS  product=%d  redis_latency=%.1fms", product_id, redis_latency_ms)

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

    # Step 3: Repopulate Redis
    # By now, hundreds of other requests have already also missed the cache
    await cache_set(cache_key, product, ttl=settings.CACHE_TTL_SECONDS)

    return product


class CheckoutError(Exception):
    pass


async def checkout(product_id: int, quantity: int = 1) -> dict[str, Any]:
    """
    Simulate checkout. Times out during stampede → HTTP 504.

    Flow: get product → validate stock → create order (stub)
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