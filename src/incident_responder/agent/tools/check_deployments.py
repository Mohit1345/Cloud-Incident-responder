from __future__ import annotations

from incident_responder.agent.tools.base import ToolResult
from incident_responder.events.cloudwatch_alarm import CloudWatchAlarmEvent
from incident_responder.sandbox.mock_registry import MockRegistry, is_sandbox


def check_recent_deployments_and_configs(event: CloudWatchAlarmEvent, use_case_id: str) -> ToolResult:
    """Check recent deployments and configuration changes correlated with the incident."""
    registry = MockRegistry(use_case_id)

    if is_sandbox():
        deployments = registry.load_json("deployments.json")
        configs = registry.load_json("configs.json")
    else:
        deployments = {"deployments": []}
        configs = {"config_changes": []}

    culprit = deployments.get("most_likely_culprit", {})
    retry_change = next(
        (c for c in configs.get("config_changes", []) if c.get("key") == "fraud_check.retry.max_attempts"),
        None,
    )

    return ToolResult(
        tool="check_recent_deployments_and_configs",
        success=True,
        data={"deployments": deployments, "configs": configs, "culprit": culprit},
        summary=(
            f"Found deployment {culprit.get('deployment_id', 'unknown')} on {culprit.get('service', '?')} "
            f"({culprit.get('confidence', 0):.0%} confidence). "
            + (
                f"Config change: fraud_check.retry.max_attempts "
                f"{retry_change['previous_value']} -> {retry_change['current_value']}"
                if retry_change
                else "No config changes found"
            )
        ),
    )
