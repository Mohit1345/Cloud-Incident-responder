from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
USE_CASES_DIR = PROJECT_ROOT / "use_cases"


@dataclass(frozen=True)
class Settings:
    sandbox: bool = os.getenv("SANDBOX", "true").lower() == "true"
    use_forage_slack: bool = os.getenv("USE_FORAGE_SLACK", "true").lower() == "true"
    slack_bot_token: str = os.getenv("SLACK_BOT_TOKEN", "")
    slack_channel: str = os.getenv("SLACK_CHANNEL", "#incidents")
    slack_webhook_url: str = os.getenv("SLACK_WEBHOOK_URL", "")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")


settings = Settings()
