# Cloud Incident Responder

Autonomous incident investigation triggered by **CloudWatch alarm** events. A background job consumer routes alarms to an agent that investigates using observability, deployment, and runbook tools — then posts the resolution to Slack via **Forage's Slack MCP server**.

## Architecture

```
CloudWatch Alarm (ALARM)
    → EventBridge / SQS
        → Background Job (AlarmConsumer)
            → Agent Orchestrator
                ├── classify_incident
                ├── query_observability
                ├── check_recent_deployments_and_configs
                ├── search_runbooks
                ├── assess_remediation_risk
                └── execute_remediation
            → Slack (via Forage MCP)
```

## Use Case: Fraud Check Retry Traffic Spike

**Scenario:** `payment-service` deployment increased `fraud_check.retry.max_attempts` from **1 → 3**, causing a **~4.5× traffic spike** to `fraud-check-service`.

| Step | Tool | Finding |
|------|------|---------|
| 1 | `classify_incident` | Traffic spike, high severity |
| 2 | `query_observability` | 4520 RPM vs 1000 baseline (4.5×) |
| 3 | `check_recent_deployments_and_configs` | payment-service v2.14.3 at 16:38 UTC; retry 1→3 |
| 4 | `search_runbooks` | Revert retry config to 1 |
| 5 | `assess_remediation_risk` | Low risk, auto-approve |
| 6 | `execute_remediation` | Revert fraud_check.retry.max_attempts to 1 |

## Quick Start

```bash
# Install
pip install -e .

# Copy env config
cp .env.example .env

# Run the fraud check use case (sandbox mocks + console Slack)
python -m incident_responder.cli run fraud_check_retry_spike

# List all use cases
python -m incident_responder.cli list

# Start background worker
python -m incident_responder.cli worker --use-case fraud_check_retry_spike
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `SANDBOX` | `true` | Mock AWS/observability/deployments |
| `USE_FORAGE_SLACK` | `true` | Post real Slack messages via Forage |
| `SLACK_BOT_TOKEN` | — | Slack bot token for posting |
| `SLACK_CHANNEL` | `#incidents` | Target channel |
| `SLACK_WEBHOOK_URL` | — | Alternative to bot token |

### Forage Slack Setup (Cursor)

1. Add Forage MCP to `.cursor/mcp.json` (see `config/mcp.json`)
2. In Cursor, run: `forage_install("@modelcontextprotocol/server-slack")`
3. Set `SLACK_BOT_TOKEN` in `.env`
4. Keep `USE_FORAGE_SLACK=true` — AWS calls stay mocked, Slack posts are real

## Adding a New Use Case

1. Create `use_cases/<your_use_case>/`:
   ```
   use_case.yaml          # metadata + trigger alarm name
   event.json             # sample CloudWatch alarm payload
   mock_data/
     metrics.json
     deployments.json
     configs.json
     runbooks/
   expected_resolution.md
   ```

2. Set `trigger.alarm_name` in `use_case.yaml` to match your CloudWatch alarm.

3. The background job auto-routes events via `resolve_use_case_for_alarm()`.

## Project Structure

```
use_cases/fraud_check_retry_spike/   # Use case fixtures
src/incident_responder/
  jobs/alarm_consumer.py             # Background job consumer
  events/cloudwatch_alarm.py         # EventBridge alarm parser
  agent/orchestrator.py              # Investigation pipeline
  agent/tools/                       # 6 agent tools
  sandbox/mock_registry.py           # Sandbox fixture loader
  integrations/slack.py              # Forage Slack posting
  cli.py                             # CLI entry point
```
