"""Tests for core parser, multi-shell formatter, SQLite store, MCP server JSON-RPC, and LLM client."""

from __future__ import annotations
import json
import tempfile
from pathlib import Path

from curl_studio.core import (
    CURL_FLAGS_DB,
    diagnose_raw_curl,
    execute_curl_spec,
    format_command_for_shell,
    parse_raw_curl_command,
)
from curl_studio.llm import LLMClient
from curl_studio.mcp import CurlStudioMCPServer
from curl_studio.storage import CommandLibraryStore, LLMSettings


def run_all_tests() -> None:
    # 1. Test Parser & Quote Doctor on User's Broken Command
    raw_user_cmd = (
        'curl -X POST "http:sdfble" -H "Content-Type: application/json" '
        '-d "{"product_id": "101", "quantity": 1, "price": 0.01}"'
    )
    warnings = diagnose_raw_curl(raw_user_cmd)
    assert len(warnings) == 2, f"Expected 2 warnings, got {warnings}"

    spec, _ = parse_raw_curl_command(raw_user_cmd, auto_fix_url=True)
    assert spec.method == "POST"
    assert spec.url == "http://sdfble"
    assert json.loads(spec.body)["product_id"] == "101"

    # 2. Test Multi-Shell Formatter
    bash_cmd = format_command_for_shell(spec, "bash")
    assert "-d '{\"product_id\": \"101\", \"quantity\": 1, \"price\": 0.01}'" in bash_cmd
    cmd_win = format_command_for_shell(spec, "cmd")
    assert '\\"product_id\\"' in cmd_win
    py_code = format_command_for_shell(spec, "python")
    assert "requests.request" in py_code

    # 3. Test Execution Engine
    res = execute_curl_spec(spec, "auto")
    assert "201 Created" in res.status_line
    assert "ORD-2026-10199" in res.pretty_body

    # 4. Test SQLite Storage & MCP JSON-RPC 2.0 Server
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_commands.db"
        store = CommandLibraryStore(db_path=db_path)
        assert len(store.list_commands()) == 4

        mcp = CurlStudioMCPServer(store=store)

        # MCP initialize
        init_resp = mcp.handle_jsonrpc_request({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        assert init_resp and init_resp["result"]["serverInfo"]["name"] == "curl-studio-mcp-server"

        # MCP tools/list
        list_resp = mcp.handle_jsonrpc_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        assert list_resp and len(list_resp["result"]["tools"]) == 6

        # MCP tools/call -> parse_and_diagnose_curl
        call_resp = mcp.handle_jsonrpc_request(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "parse_and_diagnose_curl",
                    "arguments": {"raw_command": raw_user_cmd, "auto_fix_url": True},
                },
            }
        )
        assert call_resp and not call_resp["result"]["isError"]
        payload = json.loads(call_resp["result"]["content"][0]["text"])
        assert len(payload["warnings"]) == 2
        assert payload["parsed_spec"]["url"] == "http://sdfble"

        # 5. Test LLM Client (Offline MCP Coach & Fallback)
        settings = LLMSettings(provider="builtin_coach", enable_mcp_tools=True)
        llm_client = LLMClient(settings, mcp)
        reply = llm_client.send_chat(
            f"Diagnose {raw_user_cmd}", history=[], active_spec=spec
        )
        assert reply.mcp_tool_called == "parse_and_diagnose_curl"
        assert reply.suggested_curl is not None
        assert "http://sdfble" in reply.suggested_curl

    print(
        f"All multi-module tests passed! Verified: "
        f"{len(CURL_FLAGS_DB)} flags, Parser/Quote Doctor, SQLite Store, "
        f"MCP JSON-RPC 2.0 Server (6 tools), and LLM Client."
    )


if __name__ == "__main__":
    run_all_tests()
