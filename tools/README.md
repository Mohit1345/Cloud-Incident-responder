# Datadog MCP Client

Use this helper from VS Code or the terminal to call the True Foundry Datadog MCP.

## Setup

1. Install dependencies:

```powershell
pip install -r tools/requirements.txt
```

2. Provide your True Foundry token:

```powershell
$env:TFY_MCP_TOKEN="your-truefoundry-pat"
```

Or copy `tools/.env.example` to `tools/.env` and fill in the token.

3. Optional overrides:

```powershell
$env:TFY_MCP_URL="https://gateway.truefoundry.ai/zero-shot/mcp/datadog/server"
$env:TFY_MCP_HEADERS_JSON='{"Authorization":"Bearer upstream-token"}'
```

## Usage

List available tools:

```powershell
python tools/mcp_client.py list-tools
```

Call a tool:

```powershell
python tools/mcp_client.py call search_datadog_services --args '{"query":"flash sale"}'
```

If PowerShell quoting is annoying, use the no-JSON shortcut:

```powershell
python tools/mcp_client.py call search_datadog_services --query "flash sale"
```

Or put the arguments in a file and pass `--args-file path\to\args.json`.

## VS Code

Open the repo in VS Code, then use either:
- the `Datadog MCP: List Tools` launch config
- the `Datadog MCP: Call Tool` launch config
- the `Datadog MCP: List Tools` task

Those configs read `tools/.env` if present.

The client is intentionally lightweight so you can reuse it during the demo without needing a separate app.
