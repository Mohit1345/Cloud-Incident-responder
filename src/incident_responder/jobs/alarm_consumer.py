from __future__ import annotations

import json
import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from incident_responder.agent.orchestrator import AgentOrchestrator, InvestigationResult
from incident_responder.events.cloudwatch_alarm import CloudWatchAlarmEvent
from incident_responder.sandbox.mock_registry import load_event, resolve_use_case_for_alarm

logger = logging.getLogger(__name__)


@dataclass
class AlarmJob:
    event_payload: dict[str, Any]
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    use_case_id: str | None = None


class AlarmConsumer:
    """
    Background job consumer for CloudWatch alarm events.

    In production: polls SQS / subscribes to EventBridge.
    In sandbox: reads from an in-memory queue or injects fixture events.
    """

    def __init__(self, on_complete: Callable[[InvestigationResult], None] | None = None):
        self._queue: queue.Queue[AlarmJob] = queue.Queue()
        self._orchestrator = AgentOrchestrator()
        self._on_complete = on_complete
        self._running = False
        self._thread: threading.Thread | None = None
        self._processed_ids: set[str] = set()

    def enqueue(self, event_payload: dict[str, Any], use_case_id: str | None = None) -> str:
        """Add a CloudWatch alarm event to the processing queue."""
        alarm_event = CloudWatchAlarmEvent.from_eventbridge(event_payload)
        dedupe_key = f"{alarm_event.alarm_name}:{alarm_event.timestamp.isoformat()}"

        if dedupe_key in self._processed_ids:
            logger.warning("Duplicate event skipped: %s", dedupe_key)
            return dedupe_key

        if not use_case_id:
            use_case_id = resolve_use_case_for_alarm(alarm_event.alarm_name)

        job = AlarmJob(event_payload=event_payload, use_case_id=use_case_id)
        self._queue.put(job)
        logger.info("Enqueued alarm job: %s (use_case=%s)", alarm_event.alarm_name, use_case_id)
        return dedupe_key

    def enqueue_use_case(self, use_case_id: str) -> str:
        """Inject a sandbox fixture event for a registered use case."""
        event_payload = load_event(use_case_id)
        return self.enqueue(event_payload, use_case_id=use_case_id)

    def start(self, daemon: bool = True) -> None:
        """Start the background consumer thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._consume_loop, daemon=daemon, name="alarm-consumer")
        self._thread.start()
        logger.info("Alarm consumer started")

    def stop(self, timeout: float = 10.0) -> None:
        """Stop the consumer and wait for current job to finish."""
        self._running = False
        self._queue.put(None)  # sentinel
        if self._thread:
            self._thread.join(timeout=timeout)
        logger.info("Alarm consumer stopped")

    def process_one(self, timeout: float = 5.0) -> InvestigationResult | None:
        """Process a single job synchronously (for CLI/demo)."""
        job = self._queue.get(timeout=timeout)
        if job is None:
            return None
        return self._process_job(job)

    def _consume_loop(self) -> None:
        while self._running:
            try:
                job = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if job is None:
                break
            try:
                result = self._process_job(job)
                if self._on_complete and result:
                    self._on_complete(result)
            except Exception:
                logger.exception("Failed to process alarm job")

    def _process_job(self, job: AlarmJob) -> InvestigationResult | None:
        event = CloudWatchAlarmEvent.from_eventbridge(job.event_payload)

        if not event.is_alarm:
            logger.info("Skipping non-ALARM event: %s state=%s", event.alarm_name, event.state)
            return None

        if not job.use_case_id:
            logger.error("No use case registered for alarm: %s", event.alarm_name)
            return None

        dedupe_key = f"{event.alarm_name}:{event.timestamp.isoformat()}"
        self._processed_ids.add(dedupe_key)

        logger.info("Processing: %s", event.summary())
        return self._orchestrator.investigate(event, job.use_case_id)

    @property
    def pending_count(self) -> int:
        return self._queue.qsize()
