"""
config.py — settings for the incident orchestrator service.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ENV_FILE = Path(__file__).with_name(".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    # ── Own identity ─────────────────────────────────────────────────────
    PUBLIC_BASE_URL: str = "http://localhost:8080"  # how humans/Slack reach this service

    # ── Database (same Postgres the app uses; separate schema/table) ──────
    DATABASE_URL: str = "postgresql://flashsale:flashsale@localhost:5432/flashsale"

    # ── Datadog webhook shared secret (verify inbound webhook calls) ──────
    DATADOG_WEBHOOK_TOKEN: str = "change-me"

    # ── TrueForge agent harness ─────────────────────────────────────────
    # TODO: confirm these against TrueForge's actual API docs. This adapter
    # is written defensively (see trueforge_client.py) so only that file
    # should need to change once the real contract is known.
    TRUEFORGE_API_URL: str = "http://localhost:9000"
    TRUEFORGE_API_KEY: str = ""
    TRUEFORGE_AGENT_ID: str = "incident-responder"
    TRUEFORGE_ITERATION_LIMIT: int = 15

    # Legacy direct MCP URLs. Agent Apps already own their MCP configuration.
    MCP_DIAGNOSTICS_URL: str = ""
    MCP_ACTIONS_URL: str = ""
    MCP_SLACK_URL: str = ""  # TrueForge's Slack MCP server URL, if run centrally

    # ── Slack fallback (works today without TrueForge's Slack MCP wired up) ─
    # If SLACK_WEBHOOK_URL is set, the orchestrator posts the tag itself via a
    # plain Slack Incoming Webhook. Swap to the TrueForge Slack MCP tool later
    # by implementing `tag_owner_via_trueforge_mcp` in slack_notify.py.
    SLACK_WEBHOOK_URL: str = ""

    # service (from Datadog tags) -> Slack user ID to tag
    OWNER_MAP: dict[str, str] = {
        "flashsale-app": "U0000000000",
    }
    DEFAULT_OWNER_SLACK_ID: str = "U0000000000"


settings = Settings()
