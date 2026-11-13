#!/usr/bin/env python3
"""
Entry point for the Multi-Module cURL Interactive Studio Desktop Application & MCP Server.

Usage:
  1. Launch PyQt6 Desktop GUI (with LLM Chat Dock & MCP Console):
       python main.py
  2. Run Standalone MCP Server (stdio transport for Claude Desktop / Cursor / VS Code):
       python main.py --mcp-stdio
  3. Run Standalone MCP Server over HTTP JSON-RPC:
       python main.py --mcp-http --port 8765
  4. Run Automated Self-Test Suite:
       python main.py --self-test
"""

from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))


def main() -> None:
    if "--mcp-stdio" in sys.argv:
        from curl_studio.mcp.server import CurlStudioMCPServer
        CurlStudioMCPServer().run_stdio()
        return

    if "--mcp-http" in sys.argv:
        from curl_studio.mcp.server import CurlStudioMCPServer
        port = 8765
        if "--port" in sys.argv:
            idx = sys.argv.index("--port")
            if idx + 1 < len(sys.argv):
                port = int(sys.argv[idx + 1])
        CurlStudioMCPServer().run_http(port=port)
        return

    if "--self-test" in sys.argv:
        from tests.test_suite import run_all_tests
        run_all_tests()
        return

    from curl_studio.ui.main_window import PYQT_AVAILABLE
    if not PYQT_AVAILABLE:
        print(
            "PyQt6 is required to launch the desktop GUI.\n"
            "Install it with:\n"
            "    pip install PyQt6\n"
            "Then run:\n"
            "    python main.py"
        )
        sys.exit(1)

    from PyQt6.QtWidgets import QApplication
    from curl_studio.ui.main_window import CurlStudioMainWindow

    app = QApplication(sys.argv)
    win = CurlStudioMainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
