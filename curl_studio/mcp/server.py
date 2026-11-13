"""
Model Context Protocol (MCP) Server for cURL Interactive Studio
===============================================================
Implements the JSON-RPC 2.0 MCP protocol (`initialize`, `tools/list`, `tools/call`,
`resources/list`, `resources/read`) over:
  1. Standard I/O (`python -m curl_studio.mcp.server`) for Claude Desktop, Cursor, or VS Code MCP clients
  2. Direct in-process tool dispatch (`server.call_tool(...)`) for the integrated PyQt6 LLM Chat Window
  3. Optional HTTP JSON-RPC endpoint (`python -m curl_studio.mcp.server --http --port 8765`)
"""

from __future__ import annotations
import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List, Optional

from ..core.flags_db import CURL_FLAGS_DB, search_flags
from ..core.formatter import format_command_for_shell
from ..core.models import CurlCommandSpec, HeaderItem
from ..core.parser import diagnose_raw_curl, parse_raw_curl_command
from ..core.runner import execute_curl_spec
from ..storage.command_store import CommandLibraryStore


MCP_TOOLS_SCHEMA: List[Dict[str, Any]] = [
    {
        "name": "parse_and_diagnose_curl",
        "description": (
            "Parses a raw curl command string, detects shell quote pitfalls (such as nested double quotes "
            "around JSON `-d \"{\"id\": \"101\"}\"` or missing `//` in URLs), and returns a clean specification "
            "plus properly escaped Bash, Windows CMD, PowerShell, and Python `requests` equivalents."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "raw_command": {
                    "type": "string",
                    "description": "Raw curl command string to parse and diagnose.",
                },
                "auto_fix_url": {
                    "type": "boolean",
                    "description": "Whether to automatically fix missing '//' after http: or https:.",
                    "default": True,
                },
            },
            "required": ["raw_command"],
        },
    },
    {
        "name": "build_curl_command",
        "description": (
            "Builds a properly escaped curl command from structured parameters (method, url, headers, "
            "json_body, flags) and outputs Bash, One-Liner, Windows CMD, PowerShell, and Python snippets."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "method": {"type": "string", "default": "POST"},
                "url": {"type": "string"},
                "headers": {
                    "type": "object",
                    "description": "Key-value map of HTTP headers, e.g. {'Content-Type': 'application/json'}",
                },
                "body": {
                    "type": "string",
                    "description": "Request payload body string (e.g. JSON string).",
                },
                "flags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of short flags to enable, e.g. ['-i', '-v', '-L', '-k']",
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "execute_curl_request",
        "description": (
            "Executes a curl command specification (using live system curl or trainee simulator mode) "
            "and returns HTTP status, pretty-printed JSON body, response headers (-i), and verbose handshake (-v)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "raw_command": {
                    "type": "string",
                    "description": "Raw curl command to execute (or provide url/method/body directly).",
                },
                "execution_mode": {
                    "type": "string",
                    "enum": ["auto", "real_curl", "sim_200", "sim_400", "sim_401", "sim_500"],
                    "default": "auto",
                },
            },
            "required": ["raw_command"],
        },
    },
    {
        "name": "explain_curl_flags",
        "description": (
            "Searches the 18 common cURL flags encyclopedia by flag name or keyword (e.g. '-X', '-H', '-d', "
            "'-L', '-k', 'cookie', 'proxy', 'timeout') and returns trainee-friendly explanations and tips."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "default": ""},
                "category": {"type": "string", "default": "ALL"},
            },
        },
    },
    {
        "name": "list_saved_commands",
        "description": "Lists all everyday custom cURL commands saved in the user's SQLite library.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "save_custom_command",
        "description": "Saves a cURL command to the persistent SQLite everyday library.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Label for the saved command"},
                "raw_command": {"type": "string", "description": "Raw curl command string to parse and save"},
            },
            "required": ["name", "raw_command"],
        },
    },
]


class CurlStudioMCPServer:
    """Core MCP server handler supporting both stdio JSON-RPC 2.0 and in-app tool execution."""

    def __init__(self, store: Optional[CommandLibraryStore] = None) -> None:
        self.store = store or CommandLibraryStore()

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Executes an MCP tool by name and returns structured data."""
        if name == "parse_and_diagnose_curl":
            raw_cmd = str(arguments.get("raw_command", ""))
            auto_fix = bool(arguments.get("auto_fix_url", True))
            spec, warnings = parse_raw_curl_command(raw_cmd, auto_fix_url=auto_fix)
            if not any(h.key.lower() == "content-type" for h in spec.headers) and spec.body.strip().startswith("{"):
                spec.headers.insert(0, HeaderItem("Content-Type", "application/json", True))
            return {
                "warnings": warnings,
                "parsed_spec": spec.to_dict(),
                "formatted": {
                    "bash_multiline": format_command_for_shell(spec, "bash"),
                    "bash_oneline": format_command_for_shell(spec, "oneline"),
                    "windows_cmd": format_command_for_shell(spec, "cmd"),
                    "powershell": format_command_for_shell(spec, "ps"),
                    "python_requests": format_command_for_shell(spec, "python"),
                },
            }

        if name == "build_curl_command":
            method = str(arguments.get("method", "POST")).upper()
            url = str(arguments.get("url", "http://localhost"))
            hdrs_dict = arguments.get("headers") or {}
            body = str(arguments.get("body", ""))
            short_flags = arguments.get("flags") or ["-i"]

            short_to_id = {f.short: f.flag_id for f in CURL_FLAGS_DB if f.toggleable}
            flags_map = {short_to_id[s]: True for s in short_flags if s in short_to_id}
            headers_list = [HeaderItem(str(k), str(v), True) for k, v in hdrs_dict.items()]

            spec = CurlCommandSpec(
                name="MCP Built Command",
                method=method,
                url=url,
                headers=headers_list,
                body=body,
                flags=flags_map,
            )
            return {
                "spec": spec.to_dict(),
                "bash_multiline": format_command_for_shell(spec, "bash"),
                "bash_oneline": format_command_for_shell(spec, "oneline"),
                "windows_cmd": format_command_for_shell(spec, "cmd"),
                "powershell": format_command_for_shell(spec, "ps"),
                "python_requests": format_command_for_shell(spec, "python"),
            }

        if name == "execute_curl_request":
            raw_cmd = str(arguments.get("raw_command", ""))
            mode = str(arguments.get("execution_mode", "auto"))
            spec, warnings = parse_raw_curl_command(raw_cmd, auto_fix_url=True)
            res = execute_curl_spec(spec, execution_mode=mode)
            return {
                "warnings": warnings,
                "result": res.to_dict(),
            }

        if name == "explain_curl_flags":
            q = str(arguments.get("query", ""))
            cat = str(arguments.get("category", "ALL"))
            matches = search_flags(q, cat)
            return {
                "count": len(matches),
                "flags": [m.to_dict() for m in matches],
            }

        if name == "list_saved_commands":
            items = self.store.list_commands()
            return {
                "count": len(items),
                "commands": [
                    {
                        "id": row_id,
                        "name": spec.name,
                        "method": spec.method,
                        "url": spec.url,
                        "bash_oneline": format_command_for_shell(spec, "oneline"),
                    }
                    for row_id, spec in items
                ],
            }

        if name == "save_custom_command":
            label = str(arguments.get("name", "Custom MCP Command"))
            raw_cmd = str(arguments.get("raw_command", ""))
            spec, warnings = parse_raw_curl_command(raw_cmd, auto_fix_url=True)
            spec.name = label
            saved_id = self.store.save_command(spec)
            return {
                "saved_id": saved_id,
                "name": spec.name,
                "warnings_fixed": warnings,
                "bash_oneline": format_command_for_shell(spec, "oneline"),
            }

        raise ValueError(f"Unknown MCP tool: {name}")

    def handle_jsonrpc_request(self, req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Processes a single JSON-RPC 2.0 request dictionary according to the MCP specification."""
        method = req.get("method", "")
        req_id = req.get("id")
        params = req.get("params") or {}

        # Notifications have no id and expect no response
        if req_id is None and method.startswith("notifications/"):
            return None

        try:
            if method == "initialize":
                result = {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {
                        "name": "curl-studio-mcp-server",
                        "version": "2.0.0",
                    },
                    "capabilities": {
                        "tools": {"listChanged": False},
                        "resources": {"listChanged": False},
                    },
                }
            elif method == "tools/list":
                result = {"tools": MCP_TOOLS_SCHEMA}
            elif method == "tools/call":
                tool_name = params.get("name", "")
                tool_args = params.get("arguments") or {}
                tool_output = self.call_tool(tool_name, tool_args)
                result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(tool_output, indent=2),
                        }
                    ],
                    "isError": False,
                }
            elif method == "resources/list":
                result = {
                    "resources": [
                        {
                            "uri": "curl-studio://flags/encyclopedia",
                            "name": "Common cURL Flags Encyclopedia (18 Flags)",
                            "mimeType": "application/json",
                        },
                        {
                            "uri": "curl-studio://commands/saved",
                            "name": "Saved Everyday cURL Commands Library",
                            "mimeType": "application/json",
                        },
                    ]
                }
            elif method == "resources/read":
                uri = params.get("uri", "")
                if uri == "curl-studio://flags/encyclopedia":
                    payload = [f.to_dict() for f in CURL_FLAGS_DB]
                elif uri == "curl-studio://commands/saved":
                    payload = [
                        {"id": r_id, **spec.to_dict()}
                        for r_id, spec in self.store.list_commands()
                    ]
                else:
                    raise ValueError(f"Unknown resource URI: {uri}")
                result = {
                    "contents": [
                        {
                            "uri": uri,
                            "mimeType": "application/json",
                            "text": json.dumps(payload, indent=2),
                        }
                    ]
                }
            elif method == "ping":
                result = {}
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                }

            return {"jsonrpc": "2.0", "id": req_id, "result": result}
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32000, "message": str(exc)},
            }

    def run_stdio(self) -> None:
        """Runs the MCP server over stdin/stdout (standard MCP transport)."""
        for line in sys.stdin:
            line_str = line.strip()
            if not line_str:
                continue
            try:
                req = json.loads(line_str)
                resp = self.handle_jsonrpc_request(req)
                if resp is not None:
                    sys.stdout.write(json.dumps(resp) + "\n")
                    sys.stdout.flush()
            except Exception as exc:
                err_resp = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {exc}"},
                }
                sys.stdout.write(json.dumps(err_resp) + "\n")
                sys.stdout.flush()

    def run_http(self, host: str = "127.0.0.1", port: int = 8765) -> None:
        """Runs a lightweight HTTP JSON-RPC 2.0 endpoint for local integrations."""
        mcp_server = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                raw_body = self.rfile.read(length).decode("utf-8")
                try:
                    req = json.loads(raw_body)
                    resp = mcp_server.handle_jsonrpc_request(req) or {"ok": True}
                    body_bytes = json.dumps(resp, indent=2).encode("utf-8")
                    self.send_response(200)
                except Exception as exc:
                    body_bytes = json.dumps({"error": str(exc)}).encode("utf-8")
                    self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body_bytes)))
                self.end_headers()
                self.wfile.write(body_bytes)

            def log_message(self, format: str, *args: Any) -> None:
                pass

        httpd = HTTPServer((host, port), Handler)
        print(f"cURL Studio MCP HTTP Server listening on http://{host}:{port}/mcp")
        httpd.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="cURL Studio MCP Server (stdio & HTTP)")
    parser.add_argument("--http", action="store_true", help="Run over HTTP instead of stdio")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind host")
    parser.add_argument("--port", type=int, default=8765, help="HTTP bind port")
    args = parser.parse_args()

    server = CurlStudioMCPServer()
    if args.http:
        server.run_http(args.host, args.port)
    else:
        server.run_stdio()


if __name__ == "__main__":
    main()
