"""Utility script to provision a Datadog metric monitor for API latency.

Usage:
    DATADOG_API_KEY=xxx DATADOG_APP_KEY=yyy python scripts/create_datadog_monitor.py \
        --metric http.server.duration --service flashsale-app --env dev --threshold 2.0 --site datadoghq.eu

The script calls the Datadog v1 monitor API and creates (or optionally updates)
an alert that fires when the selected latency percentile stays above the
threshold for five minutes.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

import requests


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    scope = []
    if args.service:
        scope.append(f"service:{args.service}")
    if args.environment:
        scope.append(f"env:{args.environment}")
    if args.extra_scope:
        scope.extend(args.extra_scope)
    scope_str = ",".join(scope) if scope else "*"

    query = (
        f"{args.aggregator}({args.window}):{args.statistic}({args.metric}"
        f"{{{scope_str}}}) {args.comparator} {args.threshold}"
    )

    name = args.name or (
        f"[{args.environment}] {args.service} latency > {args.threshold}{args.unit}"
        if args.service
        else f"Latency alert for {args.metric}"
    )

    message = args.message or (
        "API latency is above the expected threshold. Investigate cache and DB usage."
        "\n\n{{#is_alert}}Latency currently above threshold{{/is_alert}}"
        "\n{{#is_recovery}}Latency recovered below threshold{{/is_recovery}}"
    )

    return {
        "name": name,
        "type": "query alert",
        "query": query,
        "message": message,
        "tags": args.tags,
        "options": {
            "include_tags": True,
            "thresholds": {"critical": args.threshold, "critical_recovery": args.recovery_threshold},
            "escalation_message": args.escalation,
            "notify_no_data": args.notify_no_data,
            "no_data_timeframe": args.no_data_timeframe,
            "renotify_interval": args.renotify,
        },
    }


def create_monitor(payload: dict[str, Any], site: str, api_key: str, app_key: str) -> dict[str, Any]:
    url = f"https://api.{site}/api/v1/monitor"
    response = requests.post(url, json=payload, headers={
        "DD-API-KEY": api_key,
        "DD-APPLICATION-KEY": app_key,
        "Content-Type": "application/json",
    }, timeout=30)
    if response.status_code >= 300:
        raise RuntimeError(f"Datadog API error {response.status_code}: {response.text}")
    return response.json()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create Datadog latency monitor")
    parser.add_argument("--metric", default="http.server.duration", help="Metric to monitor")
    parser.add_argument("--service", default="flashsale-app", help="service tag value")
    parser.add_argument("--env", dest="environment", default="dev", help="env tag value")
    parser.add_argument("--extra-scope", nargs="*", default=[], help="Additional tag filters k:v")
    parser.add_argument("--site", default=os.getenv("DD_SITE", "datadoghq.com"))
    parser.add_argument("--threshold", type=float, default=2.0, help="Critical threshold (seconds)")
    parser.add_argument("--recovery-threshold", type=float, default=1.0, help="Recovery threshold")
    parser.add_argument("--window", default="avg(last_5m)", help="Datadog evaluation window")
    parser.add_argument("--statistic", default="p95", help="Aggregation (avg, p95, etc.)")
    parser.add_argument("--aggregator", default="", help="Optional outer aggregator, e.g., avg")
    parser.add_argument("--comparator", default=">", choices=[">", "<"], help="Alert when metric is > or < threshold")
    parser.add_argument("--unit", default="s", help="Unit label for the generated monitor name")
    parser.add_argument("--tags", nargs="*", default=["team:cloud-incidents"], help="Tags to attach to the monitor")
    parser.add_argument("--name", help="Override monitor name")
    parser.add_argument("--message", help="Override monitor message")
    parser.add_argument("--escalation", default="", help="Escalation message for notifications")
    parser.add_argument("--notify-no-data", action="store_true", help="Trigger alert when no data arrives")
    parser.add_argument("--no-data-timeframe", type=int, default=10, help="Minutes of no data before alerting")
    parser.add_argument("--renotify", type=int, default=0, help="Renotify interval in minutes (0 disables)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    api_key = os.getenv("DATADOG_API_KEY") or os.getenv("DD_API_KEY")
    app_key = os.getenv("DATADOG_APP_KEY")
    if not api_key or not app_key:
        sys.exit("DATADOG_API_KEY/DD_API_KEY and DATADOG_APP_KEY env vars are required")

    payload = build_payload(args)
    result = create_monitor(payload, args.site, api_key, app_key)
    print(f"Created monitor {result.get('id')} - {result.get('name')}")


if __name__ == "__main__":
    main()
