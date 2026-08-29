# MCP Server: Incident Responder

Information-only MCP server for diagnosing application incidents — especially **cache stampede** problems in the Flash-Sale Simulator app.

## Tools

| Tool | What it returns |
|------|-----------------|
| get_app_metrics | Live /metrics from the app (cache hit rate, DB pool util, checkout errors) |
| get_app_logs | Recent Docker container logs for the app service |
| get_app_logs_from_file | App logs read from a local file (fallback when Docker is unavailable) |
| get_redis_info | Redis INFO stats (ops/sec, connected clients, memory) |
| get_db_pool_stats | PostgreSQL pg_stat_activity (connection states, slow queries, frequent patterns) |
| inspect_cache_key | Existence, TTL, and size of a specific Redis key |
| health_snapshot | Quick triage across app, Redis, and PostgreSQL |

---

## Prerequisites

- Python 3.10+
- The Flash-Sale app stack running (app + Redis + PostgreSQL) — started via docker compose up in the repo root
- docker CLI available on host (for get_app_logs tool)

---

## Startup

### Option A: Run directly on host (recommended for local dev)

`ash
# 1. Navigate to the server directory
cd mcp-server

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy and edit environment config
cp .env.example .env
# Edit .env to match your setup (defaults work for docker-compose on localhost)

# 4. Start the server
python server.py
`

You should see output similar to:

`
INFO:     Started server process [12345]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8001 (Press CTRL+C to quit)
`

The server exposes the MCP SSE endpoint at:
`
http://localhost:8001/sse
`

### Option B: Run via Docker (isolated, same network as app)

Add this service to the root docker-compose.yml:

`yaml
  mcp-server:
    build:
      context: ./mcp-server
      dockerfile: Dockerfile
    ports:
      - "8001:8001"
    environment:
      APP_URL: http://app:8000
      REDIS_URL: redis://redis:6379/0
      DB_HOST: postgres
      DB_PORT: 5432
      DB_USER: flashsale
      DB_PASSWORD: flashsale
      DB_NAME: flashsale
      APP_CONTAINER: cloud-incident-responder-app-1
    depends_on:
      - app
      - redis
      - postgres
`

Then rebuild and start:

`ash
docker compose up -d --build mcp-server
`

Verify it is running:

`ash
curl http://localhost:8001/sse
# Should return an SSE stream header (keeps connection open)
`

---

## Configuration

Environment variables (set in .env or passed to container):

| Variable | Default | Description |
|----------|---------|-------------|
| APP_URL | http://localhost:8000 | Flash-Sale app base URL |
| REDIS_URL | edis://localhost:6379/0 | Redis connection string |
| DB_HOST | localhost | PostgreSQL host |
| DB_PORT | 5432 | PostgreSQL port |
| DB_USER | lashsale | PostgreSQL user |
| DB_PASSWORD | lashsale | PostgreSQL password |
| DB_NAME | lashsale | PostgreSQL database |
| APP_CONTAINER | cloud-incident-responder-app-1 | Docker container name for get_app_logs |
| LOG_FILE_PATH | *(empty)* | Optional local log file for get_app_logs_from_file |

---


---

## Docker Access for get_app_logs

The get_app_logs tool runs docker logs <container> via subprocess. Docker CLI access depends on **where** the MCP server runs:

### Scenario A: MCP server runs on host (recommended)

The server process has direct access to docker CLI. No special setup needed.

`ash
cd mcp-server
python server.py
`

### Scenario B: MCP server runs inside Docker

Mount the Docker socket into the container so docker CLI inside can talk to the host daemon:

`yaml
  mcp-server:
    build:
      context: ./mcp-server
      dockerfile: Dockerfile
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock   # <-- required for get_app_logs
    ...
`

### Scenario C: Docker CLI is unavailable (sandboxed / restricted environments)

If docker logs fails with *"Access is denied"* or *"Docker CLI not found"*, the tool returns a descriptive error. In this case, use get_app_logs_from_file instead:

1. Configure the app to write logs to a file (mount a volume in docker-compose.yml):
   `yaml
   app:
     volumes:
       - ./logs:/app/logs
     environment:
       LOG_FILE_PATH: /app/logs/app.log
   `

2. Set LOG_FILE_PATH in the MCP server's .env:
   `
   LOG_FILE_PATH=C:\Users\z004zcyp\...
   `

3. The agent calls get_app_logs_from_file instead of get_app_logs.

### Verify Docker access

Before starting the MCP server, confirm docker works from the same shell:

`ash
docker ps --format "table {{.Names}}\t{{.Status}}"
`

If this fails, get_app_logs will also fail. Fix Docker access or switch to get_app_logs_from_file.

---
## Connecting in TrueForge / Any MCP Harness

Point your agent harness at the SSE endpoint:

`yaml
mcp_servers:
  - name: incident-responder
    url: http://localhost:8001/sse
`

Use the system prompt from gent-prompt.md in your harness configuration to guide the agent's diagnostic workflow.

---

## Verifying the Server

Quick health check with curl:

`ash
# The server itself does not expose a health endpoint,
# but you can verify SSE connectivity:
curl -N http://localhost:8001/sse
`

To test individual tools, use the MCP inspector or any MCP client:

`ash
# Using the official MCP inspector (if installed)
npx @anthropics/mcp-inspector --server http://localhost:8001/sse
`

---

## Demo Flow

1. Start the full stack:
   `ash
   cd C:\Users\z004zcyp\OneDrive - Siemens AG\Desktop\Hackathon\Cloud-Incident-responder
   docker compose up -d
   cd mcp-server
   python server.py
   `

2. Run flash-sale load test:
   `ash
   k6 run loadtest/flash_sale.js
   `

3. Agent receives JIRA ticket: *"Response time 20ms → 10s"*

4. Agent calls get_app_metrics → sees cache_hit_rate_pct: 4.2, db_pool_utilization_pct: 100

5. Agent calls get_app_logs with grep=CACHE MISS → sees 400 misses on product:123 within 200ms

6. Agent calls inspect_cache_key with key=product:123 → xists: false

7. Agent calls get_redis_info → connected_clients: 147 (spike)

8. Agent calls get_db_pool_stats → 50x SELECT ... WHERE id = 123 queries > 500ms

9. **Agent RCA**: Cache stampede on hot key product:123 — cache expired under load, all requests hit DB simultaneously.

