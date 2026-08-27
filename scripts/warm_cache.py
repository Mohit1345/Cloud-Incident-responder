"""
warm_cache.py — Pre-warm the hot product into Redis for a healthy baseline.
"""

import asyncio
import json
import os

import asyncpg
import redis.asyncio as aioredis

DATABASE_URL   = os.getenv("DATABASE_URL",   "postgresql://flashsale:flashsale@localhost:5432/flashsale")
REDIS_URL      = os.getenv("REDIS_URL",      "redis://localhost:6379/0")
HOT_PRODUCT_ID = int(os.getenv("HOT_PRODUCT_ID", "123"))
CACHE_TTL      = int(os.getenv("CACHE_TTL_SECONDS", "10"))


async def warm():
    print(f"Fetching product {HOT_PRODUCT_ID} from DB...")
    conn = await asyncpg.connect(DATABASE_URL)
    row  = await conn.fetchrow(
        "SELECT id, name, price, sale_price, stock, description FROM products WHERE id = $1",
        HOT_PRODUCT_ID,
    )
    await conn.close()

    if row is None:
        print("ERROR: Product not found. Run seed_db.py first.")
        return

    product   = dict(row)
    cache_key = f"product:{HOT_PRODUCT_ID}"

    r = aioredis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)
    await r.set(cache_key, json.dumps(product), ex=CACHE_TTL)
    ttl = await r.ttl(cache_key)
    await r.aclose()

    print(f"Cached: key={cache_key}  ttl={ttl}s")
    print("Baseline established. Redis hit rate should be ~99%.")


if __name__ == "__main__":
    asyncio.run(warm())