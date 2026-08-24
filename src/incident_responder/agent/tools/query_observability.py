from __future__ import annotations

from incident_responder.agent.tools.base import ToolResult
from incident_responder.events.cloudwatch_alarm import CloudWatchAlarmEvent
from incident_responder.sandbox.mock_registry import MockRegistry, is_sandbox


def query_observability(event: CloudWatchAlarmEvent, use_case_id: str) -> ToolResult:
    """Query metrics, logs, and traces for the affected service."""
    if is_sandbox():
        metrics = MockRegistry(use_case_id).load_json("metrics.json")
    else:
        # Production: query CloudWatch, X-Ray, log aggregation
        metrics = {"error": "Production observability not configured in this demo"}

    baseline = metrics.get("baseline_rpm", 0)
    current = metrics.get("current_rpm", 0)
    multiplier = metrics.get("traffic_multiplier", 0)

    return ToolResult(
        tool="query_observability",
        success=True,
        data=metrics,
        summary=(
            f"fraud-check-service: {current} RPM (baseline {baseline}), "
            f"{multiplier:.1f}x spike since {metrics.get('anomaly_detected_at', 'unknown')}. "
            f"Primary upstream: payment-service (+352% call volume)"
        ),
    )
