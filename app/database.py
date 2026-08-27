"""
database.py — asyncpg connection pool with deliberately constrained size
and artificial query latency to make the stampede visible.
"""

import asyncpg
import logging
from decimal import Decimal
from app.config import settings

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def init_db_pool() -> None:
    global _pool
    logger.info(
        "Initialising DB pool: min=%d max=%d delay=%.1fs",
        settings.DB_POOL_MIN_SIZE,
        settings.DB_POOL_MAX_SIZE,
        settings.DB_ARTIFICIAL_DELAY_SECONDS,
    )
    _pool = await asyncpg.create_pool(
        dsn=settings.DATABASE_URL,
        min_size=settings.DB_POOL_MIN_SIZE,
        max_size=settings.DB_POOL_MAX_SIZE,
        command_timeout=10,
    )
    logger.info("DB pool ready.")


async def close_db_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialised. Call init_db_pool() first.")
    return _pool


async def fetch_product(product_id: int) -> dict | None:
    pool = get_pool()
    delay = settings.DB_ARTIFICIAL_DELAY_SECONDS

    try:
        async with pool.acquire(timeout=5.0) as conn:   # ← add timeout=5.0
            row = await conn.fetchrow(
                """
                SELECT id, name, price, sale_price, stock, description
                FROM   products
                WHERE  id = $1
                AND    pg_sleep($2) IS NOT NULL
                """,
                product_id,
                delay,
            )
    except asyncpg.TooManyConnectionsError:
        logger.error("DB pool exhausted for product=%d", product_id)
        raise
    except asyncpg.exceptions.TooManyConnectionsError:
        logger.error("DB pool exhausted for product=%d", product_id)
        raise

    if row is None:
        return None

    from decimal import Decimal
    result = {}
    for key, val in dict(row).items():
        result[key] = float(val) if isinstance(val, Decimal) else val
    return result


async def fetch_pool_stats() -> dict:
    pool = get_pool()
    return {
        "pool_size":            pool.get_size(),
        "pool_free":            pool.get_idle_size(),
        "pool_used":            pool.get_size() - pool.get_idle_size(),
        "pool_max":             settings.DB_POOL_MAX_SIZE,
        "pool_utilization_pct": round(
            (pool.get_size() - pool.get_idle_size()) / settings.DB_POOL_MAX_SIZE * 100, 1
        ),
    }