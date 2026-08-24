from __future__ import annotations

from incident_responder.agent.tools.base import ToolResult
from incident_responder.events.cloudwatch_alarm import CloudWatchAlarmEvent
from incident_responder.sandbox.mock_registry import MockRegistry, is_sandbox


def search_runbooks(event: CloudWatchAlarmEvent, use_case_id: str, query: str = "") -> ToolResult:
    """Search runbooks for remediation guidance matching the incident."""
    registry = MockRegistry(use_case_id)

    if is_sandbox():
        runbooks = registry.load_runbooks()
    else:
        runbooks = []

    search_terms = query.lower() or f"{event.alarm_name} traffic spike retry"
    matched = []
    for rb in runbooks:
        content_lower = rb["content"].lower()
        score = sum(1 for term in search_terms.split() if term in content_lower)
        if score > 0 or not query:
            matched.append({**rb, "relevance_score": score or 1})

    matched.sort(key=lambda r: r["relevance_score"], reverse=True)
    top = matched[0] if matched else None

    remediation_steps = []
    if top:
        for line in top["content"].splitlines():
            if line.strip().startswith(("1.", "2.", "3.", "- Revert", "- Increase")):
                remediation_steps.append(line.strip())

    return ToolResult(
        tool="search_runbooks",
        success=bool(matched),
        data={"matched_runbooks": matched, "top_runbook": top, "remediation_steps": remediation_steps},
        summary=(
            f"Found runbook '{top['title']}' - recommended: revert fraud_check.retry.max_attempts to 1"
            if top
            else "No matching runbooks found"
        ),
    )
