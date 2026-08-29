"""
MCP Server: Incident Responder
Provides information-only tools for diagnosing application issues,
especially cache stampede incidents in the Flash-Sale Simulator app.

Tools:
- get_app_metrics         -> Pulls /metrics from the app HTTP endpoint
- get_app_logs            -> Tails Docker container logs for the app service
- get_app_logs_from_file  -> Reads app logs from a local log file
- get_redis_info          -> Queries Redis INFO command
- get_db_pool_stats       -> Queries PostgreSQL pg_stat_activity and pool stats
- inspect_cache_key       -> Checks existence, TTL, and size of a Redis key
- health_snapshot         -> Aggregated health check across app/Redis/DB
"""

import json
import os
import re
import subprocess
import time
from typing import Any

import httpx
import redis
from mcp.server.fastmcp import FastMCP

# ── Configuration ──────────────────────────────────────────────────────────
APP_URL        = os.getenv("APP_URL", "http://localhost:8000")
REDIS_URL      = os.getenv("REDIS_URL", "redis://localhost:6379/0")
DB_HOST        = os.getenv("DB_HOST", "localhost")
DB_PORT        = int(os.getenv("DB_PORT", "5432"))
DB_USER        = os.getenv("DB_USER", "flashsale")
DB_PASSWORD    = os.getenv("DB_PASSWORD", "flashsale")
DB_NAME        = os.getenv("DB_NAME", "flashsale")
APP_CONTAINER  = os.getenv("APP_CONTAINER", "cloud-incident-responder-app-1")
DB_CONTAINER   = os.getenv("DB_CONTAINER", "cloud-incident-responder-postgres-1")
LOG_FILE_PATH  = os.getenv("LOG_FILE_PATH", "")

mcp = FastMCP("incident-responder", host="0.0.0.0", port=8001)

# ── Helper: Docker logs ────────────────────────────────────────────────────
def _docker_logs(container: str, lines: int = 100, since: str = "") -> str:
    """Tail logs from a Docker container. Falls back gracefully."""
    cmd = ["docker", "logs", "--tail", str(lines)]
    if since:
        cmd += ["--since", since]
    cmd.append(container)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return result.stdout
        return f"Docker logs error (container={container}): {result.stderr}"
    except FileNotFoundError:
        return f"Docker CLI not found. Cannot read logs from container '{container}'."
    except subprocess.TimeoutExpired:
        return f"Docker logs timed out for container '{container}'."
    except Exception as exc:
        return f"Unexpected error reading Docker logs: {exc}"


# ── Helper: Redis client ───────────────────────────────────────────────────
def _redis_client() -> redis.Redis:
    return redis.from_url(REDIS_URL, decode_responses=True)


# ═══════════════════════════════════════════════════════════════════════════
# Tool 1: get_app_metrics
# ═══════════════════════════════════════════════════════════════════════════
@mcp.tool()
async def get_app_metrics() -> dict:
    """
    Fetches live application metrics from the /metrics endpoint.
    Returns: cache hits/misses, hit rate, DB pool stats, checkout errors, uptime.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{APP_URL}/metrics")
            resp.raise_for_status()
            return resp.json()
    except httpx.ConnectError:
        return {"error": "Cannot connect to app. Is it running?", "url": f"{APP_URL}/metrics"}
    except httpx.HTTPStatusError as exc:
        return {"error": f"App returned {exc.response.status_code}", "url": f"{APP_URL}/metrics"}
    except Exception as exc:
        return {"error": str(exc), "url": f"{APP_URL}/metrics"}


# ═══════════════════════════════════════════════════════════════════════════
# Tool 2: get_app_logs
# ═══════════════════════════════════════════════════════════════════════════
@mcp.tool()
async def get_app_logs(lines: int = 100, since: str = "", grep: str = "") -> dict:
    """
    Retrieves recent logs from the application Docker container.
    If since is provided (e.g. '5m', '1h'), only logs since that duration are returned.
    If grep is provided, only lines containing that keyword are returned.
    """
    raw = _docker_logs(APP_CONTAINER, lines, since)
    if raw.startswith("Docker logs error") or raw.startswith("Docker CLI"):
        return {"error": raw, "source": "docker", "container": APP_CONTAINER}

    all_lines = raw.strip().split("\n") if raw.strip() else []
    if grep:
        all_lines = [ln for ln in all_lines if grep in ln]

    return {
        "container": APP_CONTAINER,
        "lines_requested": lines,
        "since": since or "all",
        "grep": grep or "none",
        "line_count": len(all_lines),
        "logs": all_lines,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Tool 3: get_app_logs_from_file
# ═══════════════════════════════════════════════════════════════════════════
@mcp.tool()
async def get_app_logs_from_file(lines: int = 100, grep: str = "") -> dict:
    """
    Reads application logs from a local file (configure via LOG_FILE_PATH env var).
    If LOG_FILE_PATH is not set, falls back to searching for common log file names
    in the workspace. If grep is provided, only matching lines are returned.
    """
    path_candidates = []
    if LOG_FILE_PATH:
        path_candidates.append(LOG_FILE_PATH)

    workspace = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for cand in ["app.log", "logs/app.log", "log/app.log", "output.log"]:
        path_candidates.append(os.path.join(workspace, cand))

    chosen_path = None
    for p in path_candidates:
        if os.path.isfile(p):
            chosen_path = p
            break

    if not chosen_path:
        return {
            "error": "No log file found. Set LOG_FILE_PATH env var or ensure app.log exists.",
            "searched": path_candidates,
        }

    try:
        with open(chosen_path, "r", encoding="utf-8") as fh:
            all_lines = fh.readlines()
        all_lines = [ln.rstrip("\n") for ln in all_lines]
        if len(all_lines) > lines:
            all_lines = all_lines[-lines:]
        if grep:
            all_lines = [ln for ln in all_lines if grep in ln]
        return {
            "file": chosen_path,
            "lines_requested": lines,
            "grep": grep or "none",
            "line_count": len(all_lines),
            "logs": all_lines,
        }
    except Exception as exc:
        return {"error": str(exc), "file": chosen_path}


# ═══════════════════════════════════════════════════════════════════════════
# Tool 4: get_redis_info
# ═══════════════════════════════════════════════════════════════════════════
@mcp.tool()
async def get_redis_info() -> dict:
    """
    Queries Redis INFO for performance and connection metrics.
    Returns: ops/sec, connected clients, memory usage, hit/miss counters, uptime.
    """
    try:
        r = _redis_client()
        info = r.info()
        stats_info = r.info("stats")
        clients_info = r.info("clients")
        memory_info = r.info("memory")

        return {
            "redis_version": info.get("redis_version", "unknown"),
            "uptime_in_seconds": info.get("uptime_in_seconds", 0),
            "connected_clients": clients_info.get("connected_clients", 0),
            "blocked_clients": clients_info.get("blocked_clients", 0),
            "instantaneous_ops_per_sec": stats_info.get("instantaneous_ops_per_sec", 0),
            "total_connections_received": stats_info.get("total_connections_received", 0),
            "total_commands_processed": stats_info.get("total_commands_processed", 0),
            "keyspace_hits": stats_info.get("keyspace_hits", 0),
            "keyspace_misses": stats_info.get("keyspace_misses", 0),
            "used_memory_human": memory_info.get("used_memory_human", "unknown"),
            "used_memory_peak_human": memory_info.get("used_memory_peak_human", "unknown"),
            "maxmemory_human": memory_info.get("maxmemory_human", "unknown"),
        }
    except redis.ConnectionError:
        return {"error": "Cannot connect to Redis. Is it running?", "url": REDIS_URL}
    except Exception as exc:
        return {"error": str(exc), "url": REDIS_URL}


# ═══════════════════════════════════════════════════════════════════════════
# Tool 5: get_db_pool_stats
# ═══════════════════════════════════════════════════════════════════════════
@mcp.tool()
async def get_db_pool_stats() -> dict:
    """
    Queries PostgreSQL for active connections, idle connections, slow queries,
    and waits. Does NOT return raw log lines — uses SQL on pg_stat_activity.
    """
    import asyncpg
    try:
        conn = await asyncpg.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            timeout=10,
        )

        # Total connections by state
        state_counts = await conn.fetch(
            """
            SELECT state, COUNT(*) as cnt
            FROM pg_stat_activity
            WHERE backend_type = 'client backend'
            GROUP BY state
            """
        )

        # Active queries running > 500ms
        slow_queries = await conn.fetch(
            """
            SELECT pid, usename, application_name, client_addr,
                   state, query_start, state_change,
                   NOW() - query_start AS duration,
                   query
            FROM pg_stat_activity
            WHERE state = 'active'
              AND query_start IS NOT NULL
              AND NOW() - query_start > INTERVAL '500 milliseconds'
            ORDER BY duration DESC
            LIMIT 20
            """
        )

        # Most frequent query patterns (last hour)
        frequent_queries = await conn.fetch(
            """
            SELECT query, calls, total_exec_time, mean_exec_time
            FROM pg_stat_statements
            WHERE query ILIKE '%products%'
               OR query ILIKE '%SELECT%'
            ORDER BY calls DESC
            LIMIT 10
            """
        )

        await conn.close()

        return {
            "connection_states": [
                {"state": row["state"], "count": row["cnt"]} for row in state_counts
            ],
            "slow_queries": [
                {
                    "pid": row["pid"],
                    "user": row["usename"],
                    "duration_ms": round(row["duration"].total_seconds() * 1000, 1),
                    "query": row["query"][:200],
                }
                for row in slow_queries
            ],
            "frequent_query_patterns": [
                {
                    "query": row["query"][:200],
                    "calls": row["calls"],
                    "total_exec_time_ms": round(row["total_exec_time"], 1),
                    "mean_exec_time_ms": round(row["mean_exec_time"], 1),
                }
                for row in frequent_queries
            ],
        }
    except asyncpg.PostgresError as exc:
        return {"error": f"PostgreSQL error: {exc}", "host": f"{DB_HOST}:{DB_PORT}"}
    except Exception as exc:
        return {"error": str(exc), "host": f"{DB_HOST}:{DB_PORT}"}


# ═══════════════════════════════════════════════════════════════════════════
# Tool 6: inspect_cache_key
# ═══════════════════════════════════════════════════════════════════════════
@mcp.tool()
async def inspect_cache_key(key: str) -> dict:
    """
    Inspects a single Redis cache key.
    Returns: exists (bool), TTL in seconds, memory size, value preview.
    """
    try:
        r = _redis_client()
        exists = r.exists(key) == 1
        ttl = r.ttl(key)
        if ttl == -2 or ttl == -1:
            ttl_display = "no-TTL" if ttl == -1 else "does-not-exist"
            ttl_seconds = None if ttl == -2 else -1
        else:
            ttl_display = f"{ttl}s"
            ttl_seconds = ttl

        mem = r.memory_usage(key) if exists else 0
        value_preview = None
        if exists:
            raw = r.get(key)
            if raw:
                value_preview = raw[:200] if len(raw) > 200 else raw

        return {
            "key": key,
            "exists": exists,
            "ttl_seconds": ttl_seconds,
            "ttl_display": ttl_display,
            "memory_bytes": mem,
            "value_preview": value_preview,
        }
    except redis.ConnectionError:
        return {"error": "Cannot connect to Redis. Is it running?", "url": REDIS_URL}
    except Exception as exc:
        return {"error": str(exc), "url": REDIS_URL}


# ═══════════════════════════════════════════════════════════════════════════
# Tool 7: health_snapshot
# ═══════════════════════════════════════════════════════════════════════════
@mcp.tool()
async def health_snapshot() -> dict:
    """
    Aggregated health snapshot across app, Redis, and PostgreSQL.
    Returns a quick triage view — no deep diagnosis.
    """
    snapshot = {"timestamp": time.time(), "components": {}}

    # App
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            health = await client.get(f"{APP_URL}/health")
            metrics = await client.get(f"{APP_URL}/metrics")
            snapshot["components"]["app"] = {
                "health_status": health.json() if health.status_code == 200 else "unhealthy",
                "metrics_available": metrics.status_code == 200,
            }
            if metrics.status_code == 200:
                m = metrics.json()
                snapshot["components"]["app"]["cache_hit_rate_pct"] = m.get("cache_hit_rate_pct")
                snapshot["components"]["app"]["db_pool_utilization_pct"] = m.get("db_pool_utilization_pct")
                snapshot["components"]["app"]["checkout_error_pct"] = m.get("checkout_error_pct")
    except Exception as exc:
        snapshot["components"]["app"] = {"error": str(exc)}

    # Redis
    try:
        r = _redis_client()
        info = r.info()
        snapshot["components"]["redis"] = {
            "ping": "ok",
            "connected_clients": info.get("connected_clients", 0),
            "instantaneous_ops_per_sec": info.get("instantaneous_ops_per_sec", 0),
        }
    except Exception as exc:
        snapshot["components"]["redis"] = {"error": str(exc)}

    # PostgreSQL
    try:
        import asyncpg
        conn = await asyncpg.connect(
            host=DB_HOST, port=DB_PORT, user=DB_USER,
            password=DB_PASSWORD, database=DB_NAME, timeout=5,
        )
        row = await conn.fetchrow("SELECT 1 AS alive")
        alive = row["alive"] == 1 if row else False
        active_count = await conn.fetchval(
            "SELECT COUNT(*) FROM pg_stat_activity WHERE state = 'active'"
        )
        await conn.close()
        snapshot["components"]["postgresql"] = {
            "ping": "ok" if alive else "failed",
            "active_connections": active_count,
        }
    except Exception as exc:
        snapshot["components"]["postgresql"] = {"error": str(exc)}

    return snapshot

# ═══════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    mcp.run(transport="sse")