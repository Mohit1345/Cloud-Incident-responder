"""
main.py — FastAPI application entry point.

Endpoints:
  GET  /products/{product_id}        — product lookup (vulnerable cache-aside)
  POST /checkout                     — checkout (times out during stampede)
  GET  /admin/expire-hot-product     — deterministically trigger the stampede
  GET  /admin/warm-cache             — pre-warm product:123 into Redis
  GET  /admin/reset-stats            — zero counters between runs
  GET  /metrics                      — live stats snapshot
  GET  /health                       — liveness probe
"""

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path as FilePath

from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi import FastAPI, HTTPException, Path, Query
from pydantic import BaseModel

from app.config import settings
from app.database import init_db_pool, close_db_pool, fetch_pool_stats
from app.redis_client import (
    init_redis, close_redis,
    cache_set, cache_delete,
    get_cache_stats, reset_cache_stats,
)
from app.products import get_product, checkout, CheckoutError
from app.observability import setup_otel, init_otel_providers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)

_request_count = 0
_error_count   = 0
_checkout_ok   = 0
_checkout_fail = 0
_start_time    = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=== Flash-Sale Simulator starting ===")
    init_otel_providers()
    await init_db_pool()
    await init_redis()
    logger.info("=== Ready ===")
    yield
    await close_db_pool()
    await close_redis()


app = FastAPI(
    title="Flash-Sale Simulator",
    description="Intentionally vulnerable e-commerce backend for demonstrating a Redis cache stampede.",
    version="1.0.0",
    lifespan=lifespan,
)

setup_otel(app)

_FRONTEND_DIR = FilePath(__file__).resolve().parent.parent / "frontend"
app.mount("/assets", StaticFiles(directory=_FRONTEND_DIR), name="assets")

import asyncpg

@app.exception_handler(asyncpg.exceptions.TooManyConnectionsError)
async def db_pool_exhausted_handler(request, exc):
    logger.error("DB pool exhausted: %s", exc)
    return JSONResponse(
        status_code=503,
        content={"error": "db_pool_exhausted", "message": "Database connection pool exhausted"},
    )


@app.exception_handler(TimeoutError)
async def timeout_handler(request, exc):
    logger.error("Database timeout: %s", exc)
    return JSONResponse(
        status_code=503,
        content={
            "error": "database_timeout",
            "message": (
                "Product lookup timed out while PostgreSQL was saturated. "
                "This is the cache stampede failure mode the demo is showing."
            ),
        },
    )

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    logger.error("Unhandled exception: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error", "message": str(exc)},
    )


class CheckoutRequest(BaseModel):
    product_id: int
    quantity:   int = 1


@app.get("/products/{product_id}", tags=["products"])
async def read_product(product_id: int = Path(..., ge=1)):
    global _request_count, _error_count
    _request_count += 1
    try:
        product = await get_product(product_id)
    except TimeoutError as exc:
        _error_count += 1
        logger.warning("Product lookup timeout for product=%d: %s", product_id, exc)
        raise HTTPException(
            status_code=503,
            detail={
                "error": "database_timeout",
                "message": (
                    "Product lookup timed out while PostgreSQL was saturated. "
                    "This is the cache stampede failure mode the demo is showing."
                ),
            },
        )
    if product is None:
        _error_count += 1
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found")
    return product


@app.post("/checkout", tags=["checkout"])
async def do_checkout(body: CheckoutRequest):
    global _checkout_ok, _checkout_fail, _error_count
    try:
        order = await checkout(body.product_id, body.quantity)
        _checkout_ok += 1
        return order
    except CheckoutError as exc:
        _checkout_fail += 1
        _error_count   += 1
        raise HTTPException(
            status_code=504,
            detail={"error": "checkout_timeout", "message": str(exc)},
        )


@app.get("/admin/expire-hot-product", tags=["admin"])
async def expire_hot_product():
    """Delete product:123 from Redis — triggers the stampede."""
    key     = f"product:{settings.HOT_PRODUCT_ID}"
    deleted = await cache_delete(key)
    logger.warning("ADMIN: Expired %s  >>> STAMPEDE WINDOW OPEN <<<", key)
    return {
        "action":  "expire_hot_product",
        "key":     key,
        "deleted": deleted,
        "message": "Hot product cache entry removed. Launch flash-sale traffic now.",
    }


@app.get("/admin/warm-cache", tags=["admin"])
async def warm_cache_endpoint(ttl: int = Query(default=None)):
    from app.database import fetch_product as db_fetch
    product = await db_fetch(settings.HOT_PRODUCT_ID)
    if product is None:
        raise HTTPException(status_code=404, detail="Hot product not found. Run seed_db.py first.")
    effective_ttl = ttl or settings.CACHE_TTL_SECONDS
    await cache_set(f"product:{settings.HOT_PRODUCT_ID}", product, ttl=effective_ttl)
    return {"action": "warm_cache", "product": settings.HOT_PRODUCT_ID, "ttl": effective_ttl}


@app.get("/admin/reset-stats", tags=["admin"])
async def reset_stats():
    global _request_count, _error_count, _checkout_ok, _checkout_fail
    await reset_cache_stats()
    _request_count = _error_count = _checkout_ok = _checkout_fail = 0
    return {"action": "reset_stats", "ok": True}


@app.get("/metrics", tags=["observability"])
async def metrics():
    cache_stats = await get_cache_stats()
    pool_stats  = await fetch_pool_stats()
    total_checkouts    = _checkout_ok + _checkout_fail
    checkout_error_pct = (
        round(_checkout_fail / total_checkouts * 100, 2) if total_checkouts > 0 else 0.0
    )
    return {
        "uptime_seconds":          round(time.time() - _start_time, 1),
        "requests_total":          _request_count,
        "errors_total":            _error_count,
        "cache_hits":              cache_stats["cache_hits"],
        "cache_misses":            cache_stats["cache_misses"],
        "cache_hit_rate_pct":      cache_stats["hit_rate_pct"],
        "db_pool_size":            pool_stats["pool_size"],
        "db_pool_used":            pool_stats["pool_used"],
        "db_pool_free":            pool_stats["pool_free"],
        "db_pool_max":             pool_stats["pool_max"],
        "db_pool_utilization_pct": pool_stats["pool_utilization_pct"],
        "checkout_success":        _checkout_ok,
        "checkout_failure":        _checkout_fail,
        "checkout_error_pct":      checkout_error_pct,
    }


@app.get("/health", tags=["observability"])
async def health():
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(_FRONTEND_DIR / "index.html")
