from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from incident_responder.agent.tools import (
    ToolResult,
    assess_remediation_risk,
    check_recent_deployments_and_configs,
    classify_incident,
    execute_remediation,
    query_observability,
    search_runbooks,
)
from incident_responder.events.cloudwatch_alarm import CloudWatchAlarmEvent
from incident_responder.integrations.slack import post_resolution
from incident_responder.sandbox.mock_registry import load_use_case

logger = logging.getLogger(__name__)


@dataclass
class InvestigationResult:
    use_case_id: str
    event: CloudWatchAlarmEvent
    tool_results: list[ToolResult] = field(default_factory=list)
    resolution: dict[str, Any] = field(default_factory=dict)
    slack_posted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "use_case_id": self.use_case_id,
            "alarm": self.event.alarm_name,
            "state": self.event.state,
            "tool_results": [r.to_dict() for r in self.tool_results],
            "resolution": self.resolution,
            "slack_posted": self.slack_posted,
        }


class AgentOrchestrator:
    """Runs the incident investigation agent pipeline using available tools."""

    def investigate(self, event: CloudWatchAlarmEvent, use_case_id: str) -> InvestigationResult:
        use_case = load_use_case(use_case_id)
        logger.info("Starting investigation: %s for alarm %s", use_case_id, event.alarm_name)

        result = InvestigationResult(use_case_id=use_case_id, event=event)

        # Step 1: Classify
        classify_result = classify_incident(event, use_case_id)
        result.tool_results.append(classify_result)
        logger.info("[classify_incident] %s", classify_result.summary)

        # Step 2: Query observability
        obs_result = query_observability(event, use_case_id)
        result.tool_results.append(obs_result)
        logger.info("[query_observability] %s", obs_result.summary)

        # Step 3: Check deployments & configs
        deploy_result = check_recent_deployments_and_configs(event, use_case_id)
        result.tool_results.append(deploy_result)
        logger.info("[check_deployments] %s", deploy_result.summary)

        # Step 4: Search runbooks
        runbook_result = search_runbooks(event, use_case_id, query="fraud check retry traffic spike")
        result.tool_results.append(runbook_result)
        logger.info("[search_runbooks] %s", runbook_result.summary)

        # Step 5: Assess remediation risk
        risk_result = assess_remediation_risk(event, use_case_id, proposed_action="revert_config")
        result.tool_results.append(risk_result)
        logger.info("[assess_remediation_risk] %s", risk_result.summary)

        # Step 6: Execute remediation (auto-approve if low risk)
        assessment = risk_result.data.get("assessment", {})
        auto_approve = assessment.get("auto_approve", False)
        exec_result = execute_remediation(
            event, use_case_id, action="revert_config", approved=auto_approve
        )
        result.tool_results.append(exec_result)
        logger.info("[execute_remediation] %s", exec_result.summary)

        # Build resolution summary
        result.resolution = self._build_resolution(event, use_case, result.tool_results)

        # Post to Slack via Forage (real) or console (mock)
        result.slack_posted = post_resolution(result.resolution, use_case)
        logger.info("Slack posted: %s", result.slack_posted)

        return result

    def _build_resolution(
        self,
        event: CloudWatchAlarmEvent,
        use_case: dict[str, Any],
        tool_results: list[ToolResult],
    ) -> dict[str, Any]:
        classify = next((r for r in tool_results if r.tool == "classify_incident"), None)
        obs = next((r for r in tool_results if r.tool == "query_observability"), None)
        deploy = next((r for r in tool_results if r.tool == "check_recent_deployments_and_configs"), None)
        exec_r = next((r for r in tool_results if r.tool == "execute_remediation"), None)

        configs = deploy.data.get("configs", {}) if deploy else {}
        retry_change = next(
            (c for c in configs.get("config_changes", []) if c.get("key") == "fraud_check.retry.max_attempts"),
            {},
        )

        return {
            "incident_id": f"INC-{event.alarm_name}-{event.timestamp.strftime('%Y%m%d%H%M')}",
            "title": use_case.get("name", event.alarm_name),
            "severity": classify.data.get("severity", "unknown") if classify else "unknown",
            "alarm": event.alarm_name,
            "affected_service": "fraud-check-service",
            "root_cause": (
                f"payment-service config change: fraud_check.retry.max_attempts "
                f"{retry_change.get('previous_value', '?')} -> {retry_change.get('current_value', '?')}"
            ),
            "traffic_impact": obs.summary if obs else "Unknown",
            "remediation": exec_r.summary if exec_r else "No remediation executed",
            "status": "resolved" if exec_r and exec_r.success else "investigating",
            "tool_summaries": [r.summary for r in tool_results],
        }
