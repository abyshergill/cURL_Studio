# cURL Interactive Studio, MCP Server &amp; LLM Assistant (Multi-Module PyQt6 Desktop Suite)

A modular Python/PyQt6 desktop application for building, parsing, running, and teaching `curl` commands—complete with a built-in **Model Context Protocol (MCP) Server** and an integrated **LLM Chat Dock** supporting both **Local LLMs** (Ollama, LM Studio, vLLM, llama.cpp) and **External LLM APIs** (OpenAI-compatible, Anthropic, Groq, OpenRouter).

---

## Project Architecture

```text
curl_studio_app/
├── main.py                              # Desktop GUI launcher, MCP server CLI, and self-test runner
├── requirements.txt                     # PyQt6 dependency
├── README.md                            # Setup, architecture, and MCP configuration guide
├── curl_studio/
│   ├── __init__.py
│   ├── core/                            # Pure domain logic (zero UI dependencies)
│   │   ├── models.py                    # Dataclasses: CurlFlagInfo, HeaderItem, CurlCommandSpec, ExecutionResult
│   │   ├── flags_db.py                  # 18 common cURL flags encyclopedia & search engine
│   │   ├── parser.py                    # Raw curl parser & Trainee Quote/URL Syntax Doctor
│   │   ├── formatter.py                 # Multi-shell generator (Bash, One-Liner, CMD, PowerShell, Python) & HTML anatomy
│   │   └── runner.py                    # Non-blocking system curl runner + Trainee Simulator (201/400/401/500)
│   ├── storage/                         # SQLite persistence layer (~/.curl_studio/commands.db)
│   │   └── command_store.py             # Saved everyday commands + LLM provider configuration store
│   ├── mcp/                             # Model Context Protocol (MCP) Server (JSON-RPC 2.0)
│   │   └── server.py                    # Stdio & HTTP MCP server exposing 6 tools + 2 resources
│   ├── llm/                             # Local & External LLM Client with MCP Tool Calling
│   │   └── client.py                    # Ollama, LM Studio, OpenAI-compatible, Anthropic & Offline Coach
│   └── ui/                              # PyQt6 Desktop GUI components
│       ├── main_window.py               # Main desktop window, Visual Builder, Flag Encyclopedia, MCP Console
│       └── llm_chat_widget.py           # Dockable LLM Chat window with one-click "Apply cURL to Builder"
└── tests/
    └── test_suite.py                    # End-to-end automated test suite
```

---

## Quick Start

### 1. Run the Desktop Application (PyQt6)

```bash
pip install -r requirements.txt
python main.py
```

### 2. Run the MCP Server (for Claude Desktop, Cursor, VS Code Cline, or Custom Agents)

#### Option A: Standard I/O (stdio) MCP Transport

Add this to your `claude_desktop_config.json` or `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "curl-studio": {
      "command": "python",
      "args": ["/path/to/curl_studio_app/main.py", "--mcp-stdio"]
    }
  }
}
```

#### Option B: HTTP JSON-RPC 2.0 MCP Server

```bash
python main.py --mcp-http --port 8765
```

### 3. Exposed MCP Tools (`tools/list`)

1. `parse_and_diagnose_curl`: Parses raw `curl` strings, detects nested double-quote bugs (`-d "{"id": "101"}"`) and missing `//` in URLs (`http:sdfble`), and outputs Bash, CMD, PowerShell, and Python `requests` code.
2. `build_curl_command`: Builds properly escaped `curl` commands from structured inputs (`method`, `url`, `headers`, `body`, `flags`).
3. `execute_curl_request`: Runs a `curl` command via system `curl` or Trainee Simulator and returns status, pretty JSON body, headers (`-i`), and verbose trace (`-v`).
4. `explain_curl_flags`: Searches the 18 common `curl` flags encyclopedia by flag or keyword.
5. `list_saved_commands`: Lists all everyday custom `curl` commands stored in SQLite.
6. `save_custom_command`: Parses and saves a new custom `curl` command into the SQLite library.

