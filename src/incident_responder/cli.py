from __future__ import annotations

import argparse
import json
import logging
import sys

from incident_responder.config import settings
from incident_responder.jobs.alarm_consumer import AlarmConsumer
from incident_responder.sandbox.mock_registry import list_use_cases


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def cmd_run(args: argparse.Namespace) -> int:
    """Run a use case end-to-end: inject event → investigate → post to Slack."""
    consumer = AlarmConsumer()
    consumer.enqueue_use_case(args.use_case)

    print(f"\n[*] Running use case: {args.use_case}")
    print(f"    Sandbox (mock AWS): {settings.sandbox}")
    print(f"    Forage Slack (real): {settings.use_forage_slack}\n")

    result = consumer.process_one()
    if not result:
        print("No result — event may not be in ALARM state or use case not found.")
        return 1

    print("\n[+] Investigation Complete\n")
    print(json.dumps(result.to_dict(), indent=2, default=str))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """List registered use cases."""
    cases = list_use_cases()
    if not cases:
        print("No use cases found.")
        return 0
    for case_id in cases:
        print(f"  • {case_id}")
    return 0


def cmd_worker(args: argparse.Namespace) -> int:
    """Start background alarm consumer worker."""
    consumer = AlarmConsumer(on_complete=lambda r: print(f"[OK] Resolved: {r.resolution.get('incident_id')}"))

    if args.use_case:
        consumer.enqueue_use_case(args.use_case)

    consumer.start(daemon=False)
    print(f"Alarm consumer running (sandbox={settings.sandbox}, forage_slack={settings.use_forage_slack})")
    print("Press Ctrl+C to stop.")

    try:
        while True:
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        consumer.stop()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Cloud Incident Responder")
    parser.add_argument("--log-level", default=settings.log_level)
    sub = parser.add_subparsers(dest="command")

    run_p = sub.add_parser("run", help="Run a use case investigation")
    run_p.add_argument("use_case", default="fraud_check_retry_spike", nargs="?")
    run_p.set_defaults(func=cmd_run)

    sub.add_parser("list", help="List registered use cases").set_defaults(func=cmd_list)

    worker_p = sub.add_parser("worker", help="Start background alarm consumer")
    worker_p.add_argument("--use-case", help="Inject use case event on startup")
    worker_p.set_defaults(func=cmd_worker)

    args = parser.parse_args()
    setup_logging(args.log_level)

    if not args.command:
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
