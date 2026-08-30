"""
MCP Server: Incident Responder Actions (WRITE-GATED)

Separate from mcp-server/server.py on purpose: that server is read-only
diagnostics, this one is the only thing in the whole system allowed to
change anything. Every tool here:
  1. Calls the orchestrator to confirm the session is actually 'approved'
     (never trusts the agent's own claim of approval)
  2. Only touches a fixed, whitelisted set of resources — no tool takes a
     free-form file path or shell command from the agent
  3. Reports its result back to the orchestrator so status/audit trail stay
     in one place

Tools:
- propose_changes   -> records the two-tier remediation plan, flips the
                       incident to 'awaiting_approval'
- rewarm_cache_key  -> immediate mitigation: repopulate a Redis key from
                       Postgres (same effect as scripts/warm_cache.py)
- apply_lock_fix    -> root-cause fix: replaces app/products.py with the
                       pre-written, reviewed fixed version and restarts
                       the app container
"""

import json
import logging
import os
import shutil
import subprocess
from decimal import Decimal
from typing import Any

import asyncpg
import httpx
import redis.asyncio as aioredis
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger("mcp-server-actions")
logging.basicConfig(level=logging.INFO)

ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:8080")
DATABASE_URL     = os.getenv("DATABASE_URL", "postgresql://flashsale:flashsale@localhost:5432/flashsale")
REDIS_URL        = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Fixed, whitelisted targets — never derived from agent input.
APP_PRODUCTS_PATH = os.getenv("APP_PRODUCTS_PATH", "/host-app/app/products.py")
FIXED_PATCH_PATH  = os.getenv("FIXED_PATCH_PATH", "/app/patches/products_fixed.py")
APP_CONTAINER     = os.getenv("APP_CONTAINER", "cloud-incident-responder-app-1")
RESTART_COMMAND   = ["docker", "restart", APP_CONTAINER]  # fixed command, not agent-built

mcp = FastMCP("incident-responder-actions", host="0.0.0.0", port=8002)


# ── Helper: talk to the orchestrator (source of truth for approval state) ──

async def _get_session(session_id: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{ORCHESTRATOR_URL}/sessions/{session_id}")
        resp.raise_for_status()
        return resp.json()


async def _require_approved(session_id: str) -> dict:
    session = await _get_session(session_id)
    if session.get("status") != "approved":
        raise PermissionError(
            f"Session {session_id} is not approved (status={session.get('status')}). "
            "Refusing to make any change. Wait for human approval."
        )
    return session


async def _report_applied(session_id: str, success: bool, result: dict) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(
            f"{ORCHESTRATOR_URL}/sessions/{session_id}/applied",
            json={"success": success, "result": result},
        )


async def _post_event(session_id: str, event_type: str, detail: dict) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(
            f"{ORCHESTRATOR_URL}/sessions/{session_id}/events",
            json={"type": event_type, "detail": detail},
        )


# ── Tools ────────────────────────────────────────────────────────────────

@mcp.tool()
async def propose_changes(session_id: str, root_cause: str, confidence: str,
                           immediate_mitigation_description: str,
                           root_cause_fix_description: str) -> dict:
    """Record the two-tier remediation plan for a session and move it to
    awaiting_approval. Call this once diagnosis is complete. Do NOT call
    rewarm_cache_key or apply_lock_fix until a human approves — check with
    get_session_status first."""
    body = {
        "diagnosis": {"root_cause": root_cause, "confidence": confidence},
        "proposed_changes": {
            "immediate_mitigation": {
                "action": "rewarm_cache_key",
                "description": immediate_mitigation_description,
            },
            "root_cause_fix": {
                "action": "apply_lock_fix",
                "description": root_cause_fix_description,
            },
        },
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(f"{ORCHESTRATOR_URL}/sessions/{session_id}/diagnosis", json=body)
        resp.raise_for_status()
        return resp.json()


@mcp.tool()
async def get_session_status(session_id: str) -> dict:
    """Check current session status and whether it has been approved yet.
    Call this before attempting rewarm_cache_key or apply_lock_fix."""
    return await _get_session(session_id)


@mcp.tool()
async def rewarm_cache_key(session_id: str, product_id: int, ttl_seconds: int = 60) -> dict:
    """Immediate mitigation: fetch the product fresh from Postgres and set it
    in Redis with the given TTL, stopping concurrent requests from all
    missing cache at once. Requires the session to be 'approved'."""
    try:
        await _require_approved(session_id)
    except PermissionError as exc:
        return {"ok": False, "error": str(exc)}

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        row = await conn.fetchrow(
            "SELECT id, name, price, sale_price, stock, description FROM products WHERE id = $1",
            product_id,
        )
    finally:
        await conn.close()

    if row is None:
        result = {"ok": False, "error": f"product {product_id} not found"}
        await _report_applied(session_id, False, result)
        return result

    product: dict[str, Any] = {}
    for key, val in dict(row).items():
        product[key] = float(val) if isinstance(val, Decimal) else val

    cache_key = f"product:{product_id}"
    r = aioredis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)
    try:
        await r.set(cache_key, json.dumps(product), ex=ttl_seconds)
        ttl = await r.ttl(cache_key)
    finally:
        await r.aclose()

    result = {"ok": True, "cache_key": cache_key, "ttl": ttl}
    await _post_event(session_id, "mitigation_applied", result)
    logger.info("Rewarmed %s ttl=%s for session=%s", cache_key, ttl, session_id)
    return result


@mcp.tool()
async def apply_lock_fix(session_id: str) -> dict:
    """Root-cause fix: replace app/products.py with the reviewed, locked
    version (adds a Redis lock around the cache-miss path) and restart the
    app container. Only touches that one whitelisted file and runs a fixed
    restart command — never agent-supplied paths or commands. Requires the
    session to be 'approved'."""
    try:
        await _require_approved(session_id)
    except PermissionError as exc:
        return {"ok": False, "error": str(exc)}

    try:
        shutil.copyfile(FIXED_PATCH_PATH, APP_PRODUCTS_PATH)
    except OSError as exc:
        result = {"ok": False, "error": f"failed to write patched file: {exc}"}
        await _report_applied(session_id, False, result)
        return result

    proc = subprocess.run(RESTART_COMMAND, capture_output=True, text=True, timeout=60)
    success = proc.returncode == 0
    result = {
        "ok": success,
        "patched_file": APP_PRODUCTS_PATH,
        "restart_stdout": proc.stdout,
        "restart_stderr": proc.stderr,
    }
    await _post_event(session_id, "root_cause_fix_applied", result)
    await _report_applied(session_id, success, result)
    logger.info("apply_lock_fix session=%s success=%s", session_id, success)
    return result


if __name__ == "__main__":
    mcp.run(transport="sse")
