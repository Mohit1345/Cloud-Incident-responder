from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from incident_responder.config import settings

logger = logging.getLogger(__name__)


def format_slack_message(resolution: dict[str, Any]) -> str:
    """Format investigation resolution as a Slack message."""
    lines = [
        f":warning: *Incident Resolved: {resolution.get('title', 'Unknown')}*",
        f"*ID:* `{resolution.get('incident_id', 'N/A')}`",
        f"*Severity:* {resolution.get('severity', 'unknown').upper()}",
        f"*Alarm:* `{resolution.get('alarm', 'N/A')}`",
        f"*Service:* {resolution.get('affected_service', 'N/A')}",
        "",
        "*Root Cause*",
        resolution.get("root_cause", "Under investigation"),
        "",
        "*Traffic Impact*",
        resolution.get("traffic_impact", "N/A"),
        "",
        "*Remediation*",
        resolution.get("remediation", "N/A"),
        "",
        "*Investigation Steps*",
    ]
    for i, summary in enumerate(resolution.get("tool_summaries", []), 1):
        lines.append(f"{i}. {summary}")

    lines.append("")
    lines.append(f"_Status: {resolution.get('status', 'unknown').upper()}_")
    return "\n".join(lines)


def post_resolution(resolution: dict[str, Any], use_case: dict[str, Any]) -> bool:
    """
    Post investigation resolution to Slack.

    When USE_FORAGE_SLACK=true: posts via Slack Bot API (Forage-proxied in Cursor).
    When USE_FORAGE_SLACK=false: logs to console (full sandbox).
    """
    message = format_slack_message(resolution)
    channel = use_case.get("slack", {}).get("channel", settings.slack_channel)

    if not settings.use_forage_slack:
        logger.info("[SANDBOX SLACK - console only]\nChannel: %s\n%s", channel, message)
        print("\n" + "=" * 60)
        print(f"SLACK POST (mock) -> {channel}")
        print("=" * 60)
        print(message)
        print("=" * 60 + "\n")
        return True

    return _post_via_slack_api(channel, message)


def _post_via_slack_api(channel: str, message: str) -> bool:
    """Post message using Slack Bot Token or Incoming Webhook."""
    if settings.slack_webhook_url:
        return _post_webhook(message)

    if not settings.slack_bot_token:
        logger.warning(
            "USE_FORAGE_SLACK=true but no SLACK_BOT_TOKEN or SLACK_WEBHOOK_URL set. "
            "Install Slack via Forage MCP: forage_install('@modelcontextprotocol/server-slack')"
        )
        print("\n" + "=" * 60)
        print(f"SLACK POST (Forage - token missing) -> {channel}")
        print("=" * 60)
        print(message)
        print("=" * 60 + "\n")
        return False

    try:
        response = httpx.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {settings.slack_bot_token}"},
            json={"channel": channel, "text": message, "mrkdwn": True},
            timeout=10.0,
        )
        data = response.json()
        if data.get("ok"):
            logger.info("Posted resolution to Slack channel %s", channel)
            return True
        logger.error("Slack API error: %s", data.get("error", "unknown"))
        return False
    except httpx.HTTPError as exc:
        logger.error("Failed to post to Slack: %s", exc)
        return False


def _post_webhook(message: str) -> bool:
    try:
        response = httpx.post(
            settings.slack_webhook_url,
            json={"text": message},
            timeout=10.0,
        )
        return response.status_code == 200
    except httpx.HTTPError as exc:
        logger.error("Webhook post failed: %s", exc)
        return False
