# Flash Sale Simulator

This repository demonstrates a cache stampede problem in a FastAPI app backed by PostgreSQL and Redis.

It now includes a lightweight built-in frontend at `http://localhost:8000/` that lets judges:
- warm the cache
- expire the hot key
- run a local burst of traffic
- watch the metrics degrade in real time

The intended workflow is:
- reproduce the incident in the app
- observe it first in Datadog
- corroborate with the `incident-responder` MCP
- diagnose the root cause

## What runs in the stack

- `app`: FastAPI application on `http://localhost:8000`
- `postgres`: PostgreSQL for product data
- `redis`: cache layer for hot products
- `otel-collector`, `tempo`, `loki`, `prometheus`, `grafana`, `datadog-agent`: observability stack

## Start the stack

From the repo root:

```powershell
docker compose up -d --build
```

Then open `http://localhost:8000/` in a browser.

## Seed and warm baseline data

Seed the product table:

```powershell
docker compose exec app python scripts/seed_db.py
```

Warm the hot cache key so the system starts in a healthy state:

```powershell
docker compose exec app python scripts/warm_cache.py
```

Confirm the app is alive:

```powershell
curl.exe http://localhost:8000/health
curl.exe http://localhost:8000/metrics
```

## Trigger the cache stampede demo

Expire the hot cache entry:

```powershell
curl.exe http://localhost:8000/admin/expire-hot-product
```

Generate hot-key traffic and checkout load:

```powershell
python scripts/flash_sale.py
```

The traffic script targets `product:123` heavily and will surface the stampede behavior under load.

You can also do the same from the frontend using the `Expire hot product` and `Run stampede demo` buttons.

## Datadog-first diagnosis workflow

Use the `datadog` MCP first, not `datadog-2`.

Recommended order:

1. `search_datadog_services` to confirm the app service names.
2. `search_datadog_logs` to inspect raw logs during the incident window.
3. `analyze_datadog_logs` to count errors, cache misses, or time-window spikes.
4. `search_datadog_spans` and `aggregate_spans` to verify request latency and error rate.
5. `search_datadog_metrics` and `get_datadog_metric` to inspect cache, latency, and checkout health metrics.
6. `get_change_stories` only if you suspect a deploy, config, or traffic change.

Expected incident pattern:
- cache hit rate drops sharply
- Redis misses spike on the hot key
- PostgreSQL connections climb toward pool saturation
- p95 latency increases
- checkout timeouts and errors appear

## Secondary corroboration with incident-responder

Use `incident-responder` if you want a direct system-level triage view.

Useful tools:
- `health_snapshot`
- `get_app_metrics`
- `inspect_cache_key`
- `get_redis_info`
- `get_db_pool_stats`
- `get_app_logs`

## True Foundry MCP usage

For this demo, prefer:
- `datadog` for telemetry and incident evidence
- `incident-responder` for corroboration
- `slack` and `atlassian` only if the workflow includes communication or ticketing

Ignore `datadog-2` unless you explicitly need a second Datadog account or environment.

## Datadog MCP from VS Code

If you want to call the Datadog MCP directly from VS Code, use the helper in `tools/`:

```powershell
pip install -r tools/requirements.txt
Copy-Item tools/.env.example tools/.env
# edit tools/.env and set TFY_MCP_TOKEN
python tools/mcp_client.py list-tools
python tools/mcp_client.py call search_datadog_services --args '{"query":"flash sale"}'
python tools/mcp_client.py call search_datadog_services --query "flash sale"
```

See `tools/README.md` for the full setup.

## Local MCP server

The `mcp-server/` directory contains a standalone MCP server implementation that can also be run locally.
It is optional for the Datadog-first demo flow.
