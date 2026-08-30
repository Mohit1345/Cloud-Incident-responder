"""Datadog MCP client for True Foundry.

Usage:
  python tools/mcp_client.py list-tools
  python tools/mcp_client.py call search_datadog_services --args '{"query":"flash sale"}'

Environment:
  TFY_MCP_TOKEN            Required True Foundry PAT
  TFY_MCP_URL              Remote MCP URL (defaults to Datadog MCP)
  TFY_MCP_HEADERS_JSON     Optional JSON string passed via x-tfy-mcp-headers

This script is intended to be run from VS Code's integrated terminal or debugger.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

try:
    from dotenv import load_dotenv
except ImportError:  # optional; script still works with environment variables only
    load_dotenv = None


if load_dotenv is not None:
    load_dotenv(Path(__file__).resolve().with_name(".env"))


DEFAULT_URL = "https://gateway.truefoundry.ai/zero-shot/mcp/datadog/server"


def _load_json(text: str | None, *, label: str) -> dict[str, Any]:
    if not text:
        return {}

    candidate = text.strip()

    def _coerce_scalar(value: str) -> Any:
        stripped = value.strip()
        if (stripped.startswith('"') and stripped.endswith('"')) or (stripped.startswith("'") and stripped.endswith("'")):
            return stripped[1:-1]
        lowered = stripped.lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        if lowered == "null":
            return None
        if re.fullmatch(r"-?\d+", stripped):
            return int(stripped)
        if re.fullmatch(r"-?\d+\.\d+", stripped):
            return float(stripped)
        if (stripped.startswith("{") and stripped.endswith("}")) or (stripped.startswith("[") and stripped.endswith("]")):
            try:
                return json.loads(re.sub(r'([{,]\s*)([A-Za-z_][\w-]*)(\s*:)', r'\1"\2"\3', stripped))
            except json.JSONDecodeError:
                return stripped
        return stripped

    if candidate.startswith("@{") and candidate.endswith("}"):
        items = candidate[2:-1].strip()
        result: dict[str, Any] = {}
        if items:
            for chunk in re.split(r"[;,]\s*", items):
                if not chunk.strip():
                    continue
                if "=" not in chunk:
                    raise SystemExit(
                        f"Invalid {label}: expected PowerShell hashtable entries like key=value"
                    )
                key, value = chunk.split("=", 1)
                key = key.strip().strip("'\"")
                result[key] = _coerce_scalar(value)
        return result

    if candidate.startswith("{") and candidate.endswith("}"):
        inner = candidate[1:-1].strip()
        if inner and ":" in inner and "," not in inner:
            key, value = inner.split(":", 1)
            key = key.strip().strip("'\"")
            return {key: _coerce_scalar(value)}

    try:
        value = json.loads(candidate)
    except json.JSONDecodeError as exc:
        repaired = re.sub(r'([{,]\s*)([A-Za-z_][\w-]*)(\s*:)', r'\1"\2"\3', candidate)
        if repaired != candidate:
            try:
                value = json.loads(repaired)
            except json.JSONDecodeError:
                value = None
        else:
            value = None

        if value is None:
            try:
                value = ast.literal_eval(candidate)
            except (ValueError, SyntaxError) as literal_exc:
                raise SystemExit(
                    f"Invalid {label}: {exc}. "
                    f"For PowerShell, try: --args \"{{\\\"query\\\":\\\"flash sale\\\"}}\" or --args '@{{query=\"flash sale\"}}'"
                ) from literal_exc
    if not isinstance(value, dict):
        raise SystemExit(f"Invalid {label}: expected a JSON object")
    return value


def _normalize_result(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return {k: _normalize_result(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize_result(v) for v in value]
    return value


def _build_transport() -> StreamableHttpTransport:
    token = os.getenv("TFY_MCP_TOKEN")
    if not token:
        raise SystemExit("TFY_MCP_TOKEN is required. Set it in your environment or in a local .env file.")

    url = os.getenv("TFY_MCP_URL", DEFAULT_URL)
    passthrough_headers = _load_json(os.getenv("TFY_MCP_HEADERS_JSON"), label="TFY_MCP_HEADERS_JSON")
    headers = None
    if passthrough_headers:
        headers = {"x-tfy-mcp-headers": json.dumps(passthrough_headers)}

    return StreamableHttpTransport(url=url, auth=token, headers=headers)


async def list_tools() -> None:
    transport = _build_transport()
    async with Client(transport=transport) as client:
        tools = await client.list_tools()
        for tool in tools:
            schema = getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None)
            print(f"Tool: {tool.name}")
            print(f"Description: {tool.description}")
            print(f"Parameters: {json.dumps(_normalize_result(schema), indent=2, default=str)}")
            print("-" * 80)


async def call_tool(tool_name: str, args_text: str | None) -> None:
    transport = _build_transport()
    tool_args = _load_json(args_text, label="--args") if args_text else {}

    async with Client(transport=transport) as client:
        result = await client.call_tool(tool_name, tool_args)
        print(json.dumps(_normalize_result(result), indent=2, default=str))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Datadog MCP tools through True Foundry")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list-tools", help="List available MCP tools")

    call_parser = subparsers.add_parser("call", help="Call a single MCP tool")
    call_parser.add_argument("tool_name", help="Name of the tool to call")
    call_parser.add_argument(
        "--query",
        help="Shortcut for tools that accept a query field, e.g. search_datadog_services",
    )
    call_parser.add_argument(
        "--args-file",
        type=Path,
        help="Read tool arguments from a JSON file instead of typing them inline",
    )
    call_parser.add_argument(
        "--args",
        help='Tool arguments as JSON, e.g. "{\"query\":\"service:flashsale-app\"}"',
    )

    return parser


async def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "list-tools":
        await list_tools()
    elif args.command == "call":
        tool_args = None
        if args.args_file:
            tool_args = args.args_file.read_text(encoding="utf-8")
        elif args.args:
            tool_args = args.args
        elif args.query:
            tool_args = json.dumps({"query": args.query})
        await call_tool(args.tool_name, tool_args)
    else:
        parser.print_help(sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    asyncio.run(main())
