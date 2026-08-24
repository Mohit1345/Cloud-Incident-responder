from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class CloudWatchAlarmEvent:
    alarm_name: str
    state: str
    previous_state: str
    reason: str
    timestamp: datetime
    region: str
    account: str
    metric_namespace: str = ""
    metric_name: str = ""
    target_group: str = ""
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_eventbridge(cls, payload: dict[str, Any]) -> CloudWatchAlarmEvent:
        detail = payload.get("detail", {})
        config = detail.get("configuration", {})
        metrics = config.get("metrics", [])

        namespace = ""
        metric_name = ""
        target_group = ""
        if metrics:
            metric = metrics[0].get("metricStat", {}).get("metric", {})
            namespace = metric.get("namespace", "")
            metric_name = metric.get("metricName", "")
            for dim in metric.get("dimensions", []):
                if dim.get("name") == "TargetGroup":
                    target_group = dim.get("value", "")

        state = detail.get("state", {})
        prev = detail.get("previousState", {})

        return cls(
            alarm_name=detail.get("alarmName", "unknown"),
            state=state.get("value", "UNKNOWN"),
            previous_state=prev.get("value", "UNKNOWN"),
            reason=state.get("reason", ""),
            timestamp=datetime.fromisoformat(
                state.get("timestamp", payload.get("time", "")).replace("Z", "+00:00")
            ),
            region=payload.get("region", "us-east-1"),
            account=payload.get("account", ""),
            metric_namespace=namespace,
            metric_name=metric_name,
            target_group=target_group,
            raw=payload,
        )

    @property
    def is_alarm(self) -> bool:
        return self.state == "ALARM"

    def summary(self) -> str:
        return (
            f"CloudWatch alarm '{self.alarm_name}' transitioned "
            f"{self.previous_state} -> {self.state} "
            f"({self.metric_name or 'metric'} on {self.target_group or 'target'})"
        )
