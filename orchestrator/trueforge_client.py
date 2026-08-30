"""Client for a configured TrueFoundry Agent App.

The Agent App already owns its model, prompt, MCP servers, and guardrails, so
this client only sends conversation messages and consumes the SSE response.
"""

import json
import logging
import uuid
from typing import Any

import httpx

from orchestrator.config import settings

logger = logging.getLogger(__name__)


def _agent_app_url() -> str:
    base = settings.TRUEFORGE_API_URL.rstrip("/")
    return f"{base}/api/llm/agent/{settings.TRUEFORGE_AGENT_ID}/responses"


async def _run_agent(messages: list[dict[str, str]]) -> dict[str, Any]:
    if not settings.TRUEFORGE_API_KEY:
        raise RuntimeError("TRUEFORGE_API_KEY is not configured")
    if not settings.TRUEFORGE_AGENT_ID:
        raise RuntimeError("TRUEFORGE_AGENT_ID must be the TrueFoundry Agent App ID")

    request_id = str(uuid.uuid4())
    payload = {
        "messages": messages,
        "stream": True,
        "iteration_limit": settings.TRUEFORGE_ITERATION_LIMIT,
    }
    headers = {
        "Authorization": f"Bearer {settings.TRUEFORGE_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }

    assistant_text: list[str] = []
    event_count = 0
    timeout = httpx.Timeout(connect=30, read=300, write=30, pool=30)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", _agent_app_url(), json=payload, headers=headers) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    logger.debug("Ignoring non-JSON TrueFoundry SSE event: %s", data)
                    continue
                event_count += 1
                for choice in chunk.get("choices", []):
                    content = choice.get("delta", {}).get("content")
                    if content:
                        assistant_text.append(content)

    return {
        "request_id": request_id,
        "endpoint": _agent_app_url(),
        "event_count": event_count,
        "assistant_text": "".join(assistant_text),
    }


async def start_diagnostic_session(incident_id: str, alert_payload: dict) -> dict[str, Any]:
    callback_base = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/sessions/{incident_id}"
    message = (
        f"New incident ID: {incident_id}\n\n"
        f"Alert payload:\n{json.dumps(alert_payload, indent=2)}\n\n"
        "Use the diagnostic MCP tools already configured on this Agent App. "
        "Then call propose_changes from the action MCP server using the exact "
        f"session_id {incident_id}. That tool records the diagnosis in the incident UI. "
        "Do not apply remediation in this turn. Stop after propose_changes succeeds. "
        f"The incident API is {callback_base}."
    )
    return await _run_agent([{"role": "user", "content": message}])


async def continue_approved_session(incident_id: str) -> dict[str, Any]:
    message = (
        f"Human approval has been recorded for incident/session ID {incident_id}. "
        "Call get_session_status first and verify that status is approved. If it is, "
        "apply the already-proposed remediation in order: first rewarm_cache_key, "
        "then apply_lock_fix. Use the product ID from the diagnosis/incident evidence; "
        "if it is unavailable, stop and report that instead of guessing."
    )
    return await _run_agent([{"role": "user", "content": message}])
