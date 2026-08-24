from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from incident_responder.config import USE_CASES_DIR, settings


class MockRegistry:
    """Routes tool calls to sandbox fixtures when SANDBOX=true."""

    def __init__(self, use_case_id: str):
        self.use_case_id = use_case_id
        self.fixture_dir = USE_CASES_DIR / use_case_id / "mock_data"

    def load_json(self, filename: str) -> dict[str, Any]:
        path = self.fixture_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Mock fixture not found: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def load_runbooks(self) -> list[dict[str, str]]:
        runbook_dir = self.fixture_dir / "runbooks"
        runbooks = []
        if runbook_dir.exists():
            for path in runbook_dir.glob("*.md"):
                runbooks.append({"id": path.stem, "title": path.stem.replace("_", " ").title(), "content": path.read_text(encoding="utf-8")})
        return runbooks


def load_use_case(use_case_id: str) -> dict[str, Any]:
    path = USE_CASES_DIR / use_case_id / "use_case.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_event(use_case_id: str) -> dict[str, Any]:
    path = USE_CASES_DIR / use_case_id / "event.json"
    return json.loads(path.read_text(encoding="utf-8"))


def list_use_cases() -> list[str]:
    if not USE_CASES_DIR.exists():
        return []
    return sorted(
        d.name for d in USE_CASES_DIR.iterdir()
        if d.is_dir() and (d / "use_case.yaml").exists()
    )


def resolve_use_case_for_alarm(alarm_name: str) -> str | None:
    for use_case_id in list_use_cases():
        config = load_use_case(use_case_id)
        trigger = config.get("trigger", {})
        if trigger.get("alarm_name") == alarm_name:
            return use_case_id
    return None


def is_sandbox() -> bool:
    return settings.sandbox
