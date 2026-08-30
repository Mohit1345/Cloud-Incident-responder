"""
main.py — Incident orchestrator.

Owns the incident/session state machine. This is the only service that
- receives the Datadog webhook
- starts the TrueForge diagnostic session
- fires the parallel Slack tag
- gates approval (the MCP action tools call back here to check status
  before touching anything, so approval is enforced server-side, not
  trusted from the agent's own say-so)
"""

import logging

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from orchestrator import db
from orchestrator.config import settings
from orchestrator.slack_notify import notify_owner
from orchestrator.trueforge_client import continue_approved_session, start_diagnostic_session

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("orchestrator")

app = FastAPI(title="Incident Orchestrator")


@app.on_event("startup")
async def startup() -> None:
    await db.init_pool()


@app.on_event("shutdown")
async def shutdown() -> None:
    await db.close_pool()


# ── Datadog webhook intake ─────────────────────────────────────────────────

@app.post("/webhooks/datadog")
async def datadog_webhook(request: Request, x_webhook_token: str | None = Header(default=None)):
    if x_webhook_token != settings.DATADOG_WEBHOOK_TOKEN:
        raise HTTPException(status_code=401, detail="bad webhook token")

    payload = await request.json()
    # Datadog's default webhook payload varies by template; normalise the bits we need.
    alert_id = str(payload.get("alert_id") or payload.get("id") or "unknown")

    incident = await db.create_incident(
        datadog_alert_id=alert_id,
        owner_slack_id=settings.DEFAULT_OWNER_SLACK_ID,  # refined by notify_owner below
        alert_payload=payload,
    )
    incident_id = incident["id"]
    logger.info("Incident %s created from Datadog alert %s", incident_id, alert_id)

    # Fire diagnosis + Slack tag in parallel — neither blocks the other.
    import asyncio
    asyncio.create_task(_run_diagnosis(incident_id, payload))
    asyncio.create_task(_run_notify(incident_id, payload))

    return {"incident_id": incident_id, "session_url": f"{settings.PUBLIC_BASE_URL}/sessions/{incident_id}/ui"}


async def _run_diagnosis(incident_id: str, alert_payload: dict) -> None:
    try:
        await db.set_status(incident_id, "diagnosing")
        session = await start_diagnostic_session(incident_id, alert_payload)
        await db.append_event(incident_id, {"type": "session_started", "detail": session})
    except Exception as exc:
        logger.exception("Failed to start diagnostic session for incident=%s", incident_id)
        await db.set_status(incident_id, "failed", applied_result={"error": str(exc)})


async def _run_approved_actions(incident_id: str) -> None:
    try:
        await db.append_event(incident_id, {"type": "approved_agent_started", "detail": {}})
        result = await continue_approved_session(incident_id)
        await db.append_event(incident_id, {"type": "approved_agent_finished", "detail": result})
    except Exception as exc:
        logger.exception("Failed to run approved actions for incident=%s", incident_id)
        current = await db.get_incident(incident_id)
        if current and current["status"] == "approved":
            await db.set_status(incident_id, "failed", applied_result={"error": str(exc)})


async def _run_notify(incident_id: str, alert_payload: dict) -> None:
    try:
        owner_id = await notify_owner(incident_id, alert_payload)
        pool = db.get_pool()
        await pool.execute("UPDATE incidents SET owner_slack_id = $2 WHERE id = $1", incident_id, owner_id)
    except Exception:
        logger.exception("Failed to notify owner for incident=%s", incident_id)


# ── Session read/write API (used by UI, Slack link, and the agent) ─────────

@app.get("/sessions/{incident_id}")
async def get_session(incident_id: str):
    incident = await db.get_incident(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="no such incident")
    return incident


@app.get("/sessions/{incident_id}/ui")
async def get_session_ui(incident_id: str):
    return FileResponse("orchestrator/static/session.html")


class EventIn(BaseModel):
    type: str
    detail: dict = {}


@app.post("/sessions/{incident_id}/events")
async def post_event(incident_id: str, event: EventIn):
    incident = await db.get_incident(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="no such incident")
    await db.append_event(incident_id, event.model_dump())
    return {"ok": True}


class DiagnosisIn(BaseModel):
    diagnosis: dict
    proposed_changes: dict  # expects {"immediate_mitigation": {...}, "root_cause_fix": {...}}


@app.post("/sessions/{incident_id}/diagnosis")
async def post_diagnosis(incident_id: str, body: DiagnosisIn):
    try:
        incident = await db.set_status(
            incident_id,
            "awaiting_approval",
            diagnosis=body.diagnosis,
            proposed_changes=body.proposed_changes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return incident


class ApproveIn(BaseModel):
    approved_by: str


@app.post("/sessions/{incident_id}/approve")
async def approve(incident_id: str, body: ApproveIn):
    try:
        from datetime import datetime, timezone
        incident = await db.set_status(
            incident_id, "approved",
            approved_by=body.approved_by,
            approved_at=datetime.now(timezone.utc),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    import asyncio
    asyncio.create_task(_run_approved_actions(incident_id))
    return incident


@app.post("/sessions/{incident_id}/reject")
async def reject(incident_id: str):
    try:
        incident = await db.set_status(incident_id, "rejected")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return incident


class AppliedIn(BaseModel):
    success: bool
    result: dict


@app.post("/sessions/{incident_id}/applied")
async def applied(incident_id: str, body: AppliedIn):
    try:
        new_status = "resolved" if body.success else "failed"
        # applying -> resolved/failed is allowed; also allow approved -> applying implicitly
        current = await db.get_incident(incident_id)
        if current["status"] == "approved":
            await db.set_status(incident_id, "applying")
        incident = await db.set_status(incident_id, new_status, applied_result=body.result)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return incident


@app.get("/health")
async def health():
    return JSONResponse({"status": "ok"})
