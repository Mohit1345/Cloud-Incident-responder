"""
db.py — asyncpg pool + incidents table for the orchestrator.

Uses the same Postgres instance as the flash-sale app (separate table,
zero coupling to app schema).
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import asyncpg

from orchestrator.config import settings

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
    id                  UUID PRIMARY KEY,
    datadog_alert_id    TEXT,
    status              TEXT NOT NULL DEFAULT 'received',
    owner_slack_id      TEXT,
    alert_payload       JSONB NOT NULL DEFAULT '{}'::jsonb,
    events              JSONB NOT NULL DEFAULT '[]'::jsonb,
    diagnosis           JSONB,
    proposed_changes    JSONB,
    approved_by         TEXT,
    approved_at         TIMESTAMPTZ,
    applied_result      JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents (status);
"""

# Valid state transitions — enforced in code, not just documented.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "received":          {"diagnosing", "failed"},
    "diagnosing":        {"awaiting_approval", "failed"},
    "awaiting_approval": {"approved", "rejected"},
    "approved":          {"applying", "failed"},
    "applying":          {"resolved", "failed"},
    "rejected":          set(),
    "resolved":          set(),
    "failed":            {"diagnosing"},  # allow manual retry
}


async def init_pool() -> None:
    global _pool
    _pool = await asyncpg.create_pool(dsn=settings.DATABASE_URL, min_size=1, max_size=10)
    async with _pool.acquire() as conn:
        await conn.execute(SCHEMA)
    logger.info("Orchestrator DB pool ready, schema ensured.")


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialised.")
    return _pool


def _row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    for k in ("alert_payload", "events", "diagnosis", "proposed_changes", "applied_result"):
        if isinstance(d.get(k), str):
            d[k] = json.loads(d[k])
    d["id"] = str(d["id"])
    if d.get("created_at"):
        d["created_at"] = d["created_at"].isoformat()
    if d.get("updated_at"):
        d["updated_at"] = d["updated_at"].isoformat()
    if d.get("approved_at"):
        d["approved_at"] = d["approved_at"].isoformat()
    return d


async def create_incident(datadog_alert_id: str, owner_slack_id: str, alert_payload: dict) -> dict:
    incident_id = uuid.uuid4()
    pool = get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO incidents (id, datadog_alert_id, status, owner_slack_id, alert_payload)
        VALUES ($1, $2, 'received', $3, $4::jsonb)
        RETURNING *
        """,
        incident_id, datadog_alert_id, owner_slack_id, json.dumps(alert_payload),
    )
    return _row_to_dict(row)


async def get_incident(incident_id: str) -> dict | None:
    pool = get_pool()
    row = await pool.fetchrow("SELECT * FROM incidents WHERE id = $1", uuid.UUID(incident_id))
    return _row_to_dict(row) if row else None


async def append_event(incident_id: str, event: dict) -> None:
    pool = get_pool()
    event = {**event, "ts": datetime.now(timezone.utc).isoformat()}
    await pool.execute(
        """
        UPDATE incidents
        SET events = events || $2::jsonb, updated_at = now()
        WHERE id = $1
        """,
        uuid.UUID(incident_id), json.dumps([event]),
    )


async def set_status(incident_id: str, new_status: str, **extra_fields: Any) -> dict:
    """Transition status, enforcing ALLOWED_TRANSITIONS. Extra columns (diagnosis,
    proposed_changes, approved_by, approved_at, applied_result) may be set at the
    same time to keep the state machine atomic."""
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            current = await conn.fetchrow(
                "SELECT status FROM incidents WHERE id = $1 FOR UPDATE", uuid.UUID(incident_id)
            )
            if current is None:
                raise ValueError(f"No such incident: {incident_id}")
            current_status = current["status"]
            if new_status not in ALLOWED_TRANSITIONS.get(current_status, set()):
                raise ValueError(
                    f"Illegal transition {current_status!r} -> {new_status!r} for incident {incident_id}"
                )

            set_clauses = ["status = $2", "updated_at = now()"]
            params: list[Any] = [uuid.UUID(incident_id), new_status]
            idx = 3
            for key, value in extra_fields.items():
                if key in ("diagnosis", "proposed_changes", "applied_result"):
                    set_clauses.append(f"{key} = ${idx}::jsonb")
                    params.append(json.dumps(value))
                else:
                    set_clauses.append(f"{key} = ${idx}")
                    params.append(value)
                idx += 1

            row = await conn.fetchrow(
                f"UPDATE incidents SET {', '.join(set_clauses)} WHERE id = $1 RETURNING *",
                *params,
            )
            return _row_to_dict(row)
