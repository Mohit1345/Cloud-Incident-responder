import os
import random
import time
import asyncio
import aiohttp

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")
HOT_ID = 123
CONTROL_IDS = list(range(1, 21))
HOT_RATIO = 0.9         # 90% of requests hit the hot key
CHECKOUT_RATIO = 0.5    # half of the requests attempt a checkout
CONCURRENCY = 100       # number of concurrent workers
DURATION_SECONDS = 60   # total test duration


async def worker(session, stop_time):
    stats = {"products": 0, "checkouts": 0, "errors": 0}
    while time.time() < stop_time:
        product_id = HOT_ID if random.random() < HOT_RATIO else random.choice(CONTROL_IDS)
        try:
            async with session.get(f"{BASE_URL}/products/{product_id}", timeout=12) as resp:
                if resp.status != 200:
                    stats["errors"] += 1
            stats["products"] += 1
        except Exception:
            stats["errors"] += 1

        if random.random() < CHECKOUT_RATIO:
            payload = {"product_id": product_id, "quantity": 1}
            try:
                async with session.post(f"{BASE_URL}/checkout", json=payload, timeout=15) as resp:
                    if resp.status != 200:
                        stats["errors"] += 1
                stats["checkouts"] += 1
            except Exception:
                stats["errors"] += 1
    return stats


async def main():
    stop_time = time.time() + DURATION_SECONDS
    async with aiohttp.ClientSession() as session:
        tasks = [worker(session, stop_time) for _ in range(CONCURRENCY)]
        results = await asyncio.gather(*tasks)
    combined = {"products": 0, "checkouts": 0, "errors": 0}
    for r in results:
        for key in combined:
            combined[key] += r[key]
    print(f"Finished: {combined['products']} product requests, "
          f"{combined['checkouts']} checkouts, {combined['errors']} errors")


if __name__ == "__main__":
    asyncio.run(main())