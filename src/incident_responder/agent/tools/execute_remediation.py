from __future__ import annotations

from datetime import datetime, timezone

from incident_responder.agent.tools.base import ToolResult
from incident_responder.events.cloudwatch_alarm import CloudWatchAlarmEvent
from incident_responder.config import settings


def execute_remediation(
    event: CloudWatchAlarmEvent,
    use_case_id: str,
    action: str = "revert_config",
    approved: bool = True,
) -> ToolResult:
    """Execute approved remediation. In sandbox mode, simulates the action."""
    if not approved:
        return ToolResult(
            tool="execute_remediation",
            success=False,
            data={"action": action, "status": "blocked"},
            summary="Remediation blocked - human approval required",
        )

    if action == "revert_config":
        execution = {
            "action": "revert_config",
            "target_service": "payment-service",
            "config_key": "fraud_check.retry.max_attempts",
            "from_value": 3,
            "to_value": 1,
            "method": "config_service_revert",
            "executed_at": datetime.now(timezone.utc).isoformat(),
            "status": "simulated_success" if settings.sandbox else "pending",
            "verification": {
                "expected_traffic_drop": "4.5x -> 1x within 5 min",
                "alarm_expected_state": "OK",
            },
        }
        return ToolResult(
            tool="execute_remediation",
            success=True,
            data=execution,
            summary=(
                "Reverted fraud_check.retry.max_attempts 3->1 on payment-service. "
                "Expect fraud-check traffic to normalize within 5 minutes."
            ),
        )

    return ToolResult(
        tool="execute_remediation",
        success=False,
        data={"action": action},
        summary=f"Unknown remediation action: {action}",
    )
