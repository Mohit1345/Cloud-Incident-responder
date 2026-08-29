## Datadog Integration

### 1. Configure credentials
- Populate `DD_API_KEY` (and optionally `DD_SITE`) inside `.env`. The compose file injects these variables into both the OpenTelemetry Collector and the Datadog Agent container.
- Set `DEPLOYMENT_ENV` (default `dev`) if you want OTEL traces to appear under a different Datadog environment. This value becomes the `deployment.environment` resource attribute and the agent’s `DD_ENV`.

### 2. How data flows
- The FastAPI app already exports traces/metrics/logs to the collector via OTLP. The collector now fans out to the Grafana stack (Prometheus/Tempo/Loki) **and** to Datadog through the new `datadog` exporter in `observability/otel-collector/otel-collector.yml`.
- A dedicated `datadog-agent` service tails Docker logs (Redis, Postgres, Flashsale app) as soon as the containers emit stdout/stderr. Autodiscovery labels on each workload set the Datadog `service`/`source` tags.

### 3. Bring everything up
```bash
docker compose up -d otel-collector datadog-agent
# start or restart the rest of the stack as needed
```

### 4. Verify
- Run `docker compose logs -f datadog-agent` and confirm you see `Log agent started` with zero errors.
- In Datadog, open **Logs > Live Tail** and filter by `service:flashsale-app` (or `flashsale-db` / `redis-cache`).
- Check **APM > Services** and **Metrics > Explorer** for the incoming OTLP data. If nothing shows up, ensure the collector container has the correct API key and `DEPLOYMENT_ENV` in its environment, then restart it (`docker compose up -d otel-collector`).

### 5. Troubleshooting
- `Invalid API key` in the agent logs means your `.env` value is wrong or missing.
- If logs are empty, make sure Docker Desktop/daemon lets containers read `/var/run/docker.sock` and `/var/lib/docker/containers` (required mounts already defined in `docker-compose.yml`).
- The collector only exports to Datadog when `DD_API_KEY` is non-empty; keep the local Grafana stack running regardless, so demos still work without external access.

## Datadog latency alert

You can create an API latency monitor (fires when FastAPI p95 latency exceeds 2 seconds) in two ways:

### Option A: One-click via script

```bash
export DD_SITE=datadoghq.eu
export DATADOG_API_KEY="<your key>"
export DATADOG_APP_KEY="<new application key>"
python scripts/create_datadog_monitor.py --metric http.server.duration --service flashsale-app --env dev --threshold 2 --recovery-threshold 1 --statistic p95 --window "avg(last_5m)"
```

The script hits `https://api.${DD_SITE}/api/v1/monitor` and returns the Datadog monitor ID. Edit the script arguments if you prefer a different percentile, window, or service tag.

### Option B: Manual UI steps
1. In Datadog, go to **Monitors → New Monitor → Metric**.
2. Choose the `http.server.duration` metric (it arrives via OTEL). Filter by `service:flashsale-app` and `env:dev`.
3. Set the query to `p95` over the **Last 5 minutes**. Scale/units default to seconds; confirm in the preview.
4. Alert condition: `p95 > 2s`. Recovery threshold: `1s`.
5. Add tags (`team:cloud-incidents`, `env:dev`) and a message explaining that cache stampede or DB saturation likely caused the spike.
6. Save the monitor; you’ll start seeing events in **Monitors** and receive notifications through your configured channels.

The monitor watches the OTEL-exported latency metric the same way regardless of whether you use the scripted or manual approach.
