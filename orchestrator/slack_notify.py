"""
slack_notify.py — tags the on-call owner about a new incident.

Two paths:
1. tag_owner_via_webhook() — works TODAY, no TrueForge dependency. Uses a
   plain Slack Incoming Webhook URL. This is what runs by default.
2. tag_owner_via_trueforge_mcp() — TODO stub for routing the Slack post
   through TrueForge's own Slack MCP server/tool instead, once its tool
   name and call signature are confirmed. Swap the call in notify_owner()
   when ready; nothing else in the orchestrator needs to change.
"""

import logging

import httpx

from orchestrator.config import settings

logger = logging.getLogger(__name__)


def resolve_owner_slack_id(alert_payload: dict) -> str:
    service = alert_payload.get("service") or alert_payload.get("tags", {}).get("service")
    return settings.OWNER_MAP.get(service, settings.DEFAULT_OWNER_SLACK_ID)


async def tag_owner_via_webhook(owner_slack_id: str, incident_id: str, alert_payload: dict) -> None:
    if not settings.SLACK_WEBHOOK_URL:
        logger.warning("SLACK_WEBHOOK_URL not set — skipping Slack notification for incident=%s", incident_id)
        return

    session_url = f"{settings.PUBLIC_BASE_URL}/sessions/{incident_id}/ui"
    metric = alert_payload.get("metric", "unknown metric")
    text = (
        f"*Incident detected* — <@{owner_slack_id}>\n"
        f"Metric: `{metric}` breached threshold.\n"
        f"An agent is diagnosing now. Review and approve the fix here: {session_url}"
    )

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(settings.SLACK_WEBHOOK_URL, json={"text": text})
        resp.raise_for_status()

    logger.info("Slack tag sent for incident=%s owner=%s", incident_id, owner_slack_id)


async def tag_owner_via_trueforge_mcp(owner_slack_id: str, incident_id: str, alert_payload: dict) -> None:
    """TODO: implement once TrueForge's Slack MCP tool name/signature is known.
    Likely shape: call TrueForge's generic tool-invocation endpoint with
    tool="slack.post_message" (or similar), args={channel/user, text}.
    Left unimplemented on purpose rather than guessed at."""
    raise NotImplementedError("Wire this up once TrueForge's Slack MCP tool contract is confirmed.")


async def notify_owner(incident_id: str, alert_payload: dict) -> str:
    owner_slack_id = resolve_owner_slack_id(alert_payload)
    await tag_owner_via_webhook(owner_slack_id, incident_id, alert_payload)
    return owner_slack_id
