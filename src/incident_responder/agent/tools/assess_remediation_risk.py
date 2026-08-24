from __future__ import annotations

from incident_responder.agent.tools.base import ToolResult
from incident_responder.events.cloudwatch_alarm import CloudWatchAlarmEvent


def assess_remediation_risk(
    event: CloudWatchAlarmEvent,
    use_case_id: str,
    proposed_action: str = "revert_config",
) -> ToolResult:
    """Assess risk of proposed remediation actions before execution."""
    options = {
        "revert_config": {
            "action": "Revert fraud_check.retry.max_attempts from 3 to 1 on payment-service",
            "risk_level": "low",
            "risk_score": 0.15,
            "blast_radius": "payment-service only",
            "rollback_available": True,
            "estimated_recovery_minutes": 5,
            "auto_approve": True,
            "rationale": "Reverting to last known good config; no data loss; minimal user impact",
        },
        "scale_fraud_check": {
            "action": "Scale fraud-check-service replicas from 4 to 12",
            "risk_level": "medium",
            "risk_score": 0.45,
            "blast_radius": "fraud-check-service + cost increase",
            "rollback_available": True,
            "estimated_recovery_minutes": 10,
            "auto_approve": False,
            "rationale": "Addresses symptom not root cause; higher cost; requires HITL approval",
        },
    }

    selected = options.get(proposed_action, options["revert_config"])

    return ToolResult(
        tool="assess_remediation_risk",
        success=True,
        data={"proposed_action": proposed_action, "assessment": selected, "all_options": options},
        summary=(
            f"Risk assessment for '{selected['action']}': {selected['risk_level']} "
            f"(score {selected['risk_score']:.2f}), auto_approve={selected['auto_approve']}"
        ),
    )
