from __future__ import annotations

from incident_responder.agent.tools.base import ToolResult
from incident_responder.events.cloudwatch_alarm import CloudWatchAlarmEvent
from incident_responder.sandbox.mock_registry import MockRegistry, is_sandbox


def classify_incident(event: CloudWatchAlarmEvent, use_case_id: str) -> ToolResult:
    """Classify the incident type and severity from alarm context."""
    use_case_config = MockRegistry(use_case_id)
    if is_sandbox():
        metrics = use_case_config.load_json("metrics.json")
        multiplier = metrics.get("traffic_multiplier", 1.0)
    else:
        multiplier = 1.0  # real implementation would query CloudWatch

    classification = {
        "incident_type": "traffic_spike",
        "severity": "high" if multiplier >= 3.0 else "medium",
        "affected_service": "fraud-check-service",
        "alarm_name": event.alarm_name,
        "confidence": 0.94,
        "indicators": [
            f"Request rate {multiplier:.1f}x above baseline",
            "Upstream caller pattern change detected",
            "No fraud-check-service deployment in lookback window",
        ],
    }

    return ToolResult(
        tool="classify_incident",
        success=True,
        data=classification,
        summary=(
            f"Classified as {classification['incident_type']} ({classification['severity']}) "
            f"on {classification['affected_service']} - {multiplier:.1f}x traffic spike"
        ),
    )
