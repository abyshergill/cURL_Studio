"""
Unified LLM Client for Local LLMs (Ollama / LM Studio / vLLM / llama.cpp)
and External APIs (OpenAI-compatible / Anthropic / Custom Endpoints),
with automatic MCP Tool Calling & Built-in Offline Trainee Coach fallback.
"""

from __future__ import annotations
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..core.formatter import format_command_for_shell
from ..core.models import CurlCommandSpec
from ..mcp.server import CurlStudioMCPServer, MCP_TOOLS_SCHEMA
from ..storage.command_store import LLMSettings


@dataclass
class ChatMessage:
    role: str  # 'system' | 'user' | 'assistant' | 'tool'
    content: str


@dataclass
class LLMReply:
    text: str
    provider_used: str
    mcp_tool_called: Optional[str] = None
    mcp_tool_output: Optional[Dict[str, Any]] = None
    suggested_curl: Optional[str] = None


PROVIDER_PRESETS: Dict[str, Dict[str, str]] = {
    "ollama": {
        "label": "Local LLM — Ollama (http://localhost:11434)",
        "base_url": "http://localhost:11434/v1/chat/completions",
        "default_model": "llama3.2",
    },
    "lm_studio": {
        "label": "Local LLM — LM Studio / vLLM / llama.cpp (http://localhost:1234)",
        "base_url": "http://localhost:1234/v1/chat/completions",
        "default_model": "local-model",
    },
    "openai_compat": {
        "label": "External API — OpenAI / Groq / Together / DeepSeek / OpenRouter",
        "base_url": "https://api.openai.com/v1/chat/completions",
        "default_model": "gpt-4o-mini",
    },
    "anthropic": {
        "label": "External API — Anthropic Messages API",
        "base_url": "https://api.anthropic.com/v1/messages",
        "default_model": "claude-3-5-sonnet-latest",
    },
    "builtin_coach": {
        "label": "Offline Built-in MCP Trainee Coach (Zero Network Required)",
        "base_url": "builtin://mcp-coach",
        "default_model": "curl-studio-coach-v2",
    },
}


class LLMClient:
    """
    Connects the Desktop Chat Window to either:
      1. Local LLM (Ollama / LM Studio / llama.cpp / vLLM via OpenAI-compatible HTTP endpoint)
      2. External LLM API (OpenAI, Anthropic, Groq, OpenRouter, or custom enterprise LLM gateway)
      3. Built-in Offline MCP Coach (automatically used when selected or if local/remote LLM is unreachable)
    """

    def __init__(self, settings: LLMSettings, mcp_server: CurlStudioMCPServer) -> None:
        self.settings = settings
        self.mcp = mcp_server

    def send_chat(
        self,
        user_prompt: str,
        history: List[ChatMessage],
        active_spec: Optional[CurlCommandSpec] = None,
        last_response_summary: str = "",
    ) -> LLMReply:
        # 1. Pre-execute relevant MCP tool if MCP integration is enabled
        mcp_tool_name: Optional[str] = None
        mcp_tool_data: Optional[Dict[str, Any]] = None

        if self.settings.enable_mcp_tools:
            mcp_tool_name, mcp_tool_data = self._auto_dispatch_mcp_tool(user_prompt, active_spec)

        # 2. If user selected Offline Built-in Coach, answer immediately using MCP context
        if self.settings.provider == "builtin_coach":
            return self._build_offline_coach_reply(
                user_prompt, active_spec, last_response_summary, mcp_tool_name, mcp_tool_data
            )

        # 3. Build system prompt enriched with current workspace + MCP tool output
        system_prompt = self._build_system_prompt(active_spec, last_response_summary, mcp_tool_name, mcp_tool_data)

        try:
            if self.settings.provider == "anthropic":
                reply_text = self._call_anthropic_api(system_prompt, history, user_prompt)
            else:
                reply_text = self._call_openai_compatible_api(system_prompt, history, user_prompt)

            suggested = self._extract_curl_snippet(reply_text)
            return LLMReply(
                text=reply_text,
                provider_used=f"{self.settings.provider} ({self.settings.model_name})",
                mcp_tool_called=mcp_tool_name,
                mcp_tool_output=mcp_tool_data,
                suggested_curl=suggested,
            )
        except Exception as exc:
            # Graceful fallback to Built-in MCP Coach if local Ollama or External API is offline
            fallback = self._build_offline_coach_reply(
                user_prompt, active_spec, last_response_summary, mcp_tool_name, mcp_tool_data
            )
            fallback.provider_used = f"Built-in MCP Coach (Fallback — {self.settings.provider} unreachable: {exc})"
            return fallback

    def _auto_dispatch_mcp_tool(
        self, prompt: str, active_spec: Optional[CurlCommandSpec]
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        p_low = prompt.lower()

        # Check if user pasted a raw curl command in chat
        raw_match = re.search(r"(curl(?:\.exe)?\s+[^\n`]+)", prompt, re.IGNORECASE)
        if raw_match:
            cmd_str = raw_match.group(1).strip()
            return "parse_and_diagnose_curl", self.mcp.call_tool(
                "parse_and_diagnose_curl", {"raw_command": cmd_str, "auto_fix_url": True}
            )

        # Check if user is asking about a specific flag or flags
        flag_match = re.search(r"(?:flag|what is|explain|use)\s+(-[a-zA-Z]|--[a-z-]+)", prompt, re.IGNORECASE)
        if flag_match or any(w in p_low for w in ("flag", "redirect", "insecure", "ssl", "verbose", "timeout", "proxy", "cookie")):
            q = flag_match.group(1) if flag_match else ""
            if not q:
                for kw in ("redirect", "ssl", "verbose", "timeout", "proxy", "cookie", "silent", "header", "auth"):
                    if kw in p_low:
                        q = kw
                        break
            return "explain_curl_flags", self.mcp.call_tool("explain_curl_flags", {"query": q})

        # Check if user asks to list saved commands
        if "saved" in p_low or "library" in p_low or "preset" in p_low:
            return "list_saved_commands", self.mcp.call_tool("list_saved_commands", {})

        # Default: diagnose active builder command via MCP
        if active_spec is not None:
            oneline = format_command_for_shell(active_spec, "oneline")
            return "parse_and_diagnose_curl", self.mcp.call_tool(
                "parse_and_diagnose_curl", {"raw_command": oneline, "auto_fix_url": True}
            )

        return None, None

    def _build_system_prompt(
        self,
        active_spec: Optional[CurlCommandSpec],
        last_response_summary: str,
        mcp_tool_name: Optional[str],
        mcp_tool_data: Optional[Dict[str, Any]],
    ) -> str:
        lines = [
            "You are the cURL Studio AI Assistant & Trainee Coach integrated into a PyQt6 Desktop Application.",
            "Help engineers and trainees build, debug, and understand curl commands clearly.",
            "Whenever you suggest a curl command, place it inside a ```bash ... ``` code block so the UI can load it into the Visual Builder with one click.",
        ]
        if active_spec:
            lines.append("\n[Current Visual Builder Command]:")
            lines.append(format_command_for_shell(active_spec, "oneline"))
        if last_response_summary:
            lines.append(f"\n[Last HTTP Response Summary]:\n{last_response_summary}")
        if mcp_tool_name and mcp_tool_data:
            lines.append(f"\n[MCP Server Tool `{mcp_tool_name}` Output]:\n{json.dumps(mcp_tool_data, indent=2)}")
        return "\n".join(lines)

    def _call_openai_compatible_api(
        self, system_prompt: str, history: List[ChatMessage], user_prompt: str
    ) -> str:
        messages = [{"role": "system", "content": system_prompt}]
        for m in history[-8:]:
            if m.role in ("user", "assistant"):
                messages.append({"role": m.role, "content": m.content})
        messages.append({"role": "user", "content": user_prompt})

        payload = {
            "model": self.settings.model_name,
            "messages": messages,
            "temperature": self.settings.temperature,
            "stream": False,
        }
        headers = {"Content-Type": "application/json"}
        if self.settings.api_key.strip():
            headers["Authorization"] = f"Bearer {self.settings.api_key.strip()}"

        req = urllib.request.Request(
            self.settings.base_url.strip(),
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            if "choices" in data and data["choices"]:
                return str(data["choices"][0]["message"]["content"])
            if "message" in data and "content" in data["message"]:
                return str(data["message"]["content"])
            return raw

    def _call_anthropic_api(
        self, system_prompt: str, history: List[ChatMessage], user_prompt: str
    ) -> str:
        messages = []
        for m in history[-8:]:
            if m.role in ("user", "assistant"):
                messages.append({"role": m.role, "content": m.content})
        messages.append({"role": "user", "content": user_prompt})

        payload = {
            "model": self.settings.model_name,
            "max_tokens": 1024,
            "system": system_prompt,
            "messages": messages,
        }
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
            "x-api-key": self.settings.api_key.strip(),
        }
        req = urllib.request.Request(
            self.settings.base_url.strip(),
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            blocks = data.get("content", [])
            if blocks and isinstance(blocks, list):
                return str(blocks[0].get("text", ""))
            return json.dumps(data)

    def _build_offline_coach_reply(
        self,
        user_prompt: str,
        active_spec: Optional[CurlCommandSpec],
        last_response_summary: str,
        mcp_tool_name: Optional[str],
        mcp_tool_data: Optional[Dict[str, Any]],
    ) -> LLMReply:
        """Deterministic MCP-powered assistant when working offline or in Built-in Coach mode."""
        parts: List[str] = []
        suggested_cmd: Optional[str] = None

        if mcp_tool_name == "parse_and_diagnose_curl" and mcp_tool_data:
            warnings = mcp_tool_data.get("warnings", [])
            fmt = mcp_tool_data.get("formatted", {})
            suggested_cmd = fmt.get("bash_oneline")

            if warnings:
                parts.append("### MCP Quote & Syntax Diagnosis")
                for w in warnings:
                    parts.append(f"- **Issue Detected:** {w}")
            else:
                parts.append("### MCP Command Analysis\nYour current command syntax and quote escaping look clean.")

            if fmt:
                parts.append("\n### Properly Escaped Command (Bash / Zsh)")
                parts.append(f"```bash\n{fmt.get('bash_multiline', '')}\n```")
                parts.append("\n### Windows CMD Equivalent")
                parts.append(f"```cmd\n{fmt.get('windows_cmd', '')}\n```")
                parts.append("\n### Python `requests` Snippet")
                parts.append(f"```python\n{fmt.get('python_requests', '')}\n```")

        elif mcp_tool_name == "explain_curl_flags" and mcp_tool_data:
            flags = mcp_tool_data.get("flags", [])
            parts.append(f"### MCP Flag Encyclopedia Matches ({len(flags)} found)")
            for f in flags[:6]:
                parts.append(
                    f"- **`{f['short']}` (`{f['long']}`)** — *{f['summary']}*\n"
                    f"  - **How it works:** {f['detail']}\n"
                    f"  - **Example:** `{f['example']}`\n"
                    f"  - **Trainee Tip:** {f['trainee_tip']}"
                )
            if active_spec:
                suggested_cmd = format_command_for_shell(active_spec, "oneline")

        elif mcp_tool_name == "list_saved_commands" and mcp_tool_data:
            cmds = mcp_tool_data.get("commands", [])
            parts.append(f"### Saved Everyday Commands ({len(cmds)} in SQLite Library)")
            for c in cmds:
                parts.append(f"- **{c['name']}** (`{c['method']} {c['url']}`)\n  ```bash\n  {c['bash_oneline']}\n  ```")
                if not suggested_cmd:
                    suggested_cmd = c["bash_oneline"]
        else:
            if active_spec:
                suggested_cmd = format_command_for_shell(active_spec, "oneline")
                parts.append(f"### Current Builder Command\n```bash\n{suggested_cmd}\n```")

        return LLMReply(
            text="\n\n".join(parts) if parts else "Ask me to diagnose any `curl` command, explain flags, or generate a new API request!",
            provider_used="Offline Built-in MCP Trainee Coach",
            mcp_tool_called=mcp_tool_name,
            mcp_tool_output=mcp_tool_data,
            suggested_curl=suggested_cmd,
        )

    @staticmethod
    def _extract_curl_snippet(text: str) -> Optional[str]:
        code_block = re.search(r"```(?:bash|sh|shell)?\s*(curl[\s\S]*?)```", text, re.IGNORECASE)
        if code_block:
            return code_block.group(1).strip()
        inline = re.search(r"(curl\s+-[^\n]+)", text)
        if inline:
            return inline.group(1).strip()
        return None
