"""
LLM Chat Dock / Panel Widget (Local Ollama / LM Studio + External APIs + MCP Tool Calling)
==========================================================================================
Provides:
1. Provider Configuration Bar (Ollama, LM Studio/vLLM, OpenAI-Compatible API, Anthropic, Built-in Offline Coach)
2. Editable Endpoint URL, Model Name, API Key, and "Enable MCP Server Tools" toggle
3. Quick Action Prompts ("Explain Current Command for Trainee", "Diagnose Last Response", "Fix Broken Quotes")
4. One-Click "Apply Suggested cURL to Visual Builder" button
"""

from __future__ import annotations
from typing import Callable, List, Optional

try:
    from PyQt6.QtCore import Qt, QThread, pyqtSignal
    from PyQt6.QtGui import QFont
    from PyQt6.QtWidgets import (
        QCheckBox,
        QComboBox,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QPushButton,
        QTextBrowser,
        QVBoxLayout,
        QWidget,
    )
    PYQT_AVAILABLE = True
except ImportError:
    PYQT_AVAILABLE = False

from ..core.models import CurlCommandSpec
from ..llm.client import PROVIDER_PRESETS, ChatMessage, LLMClient, LLMReply
from ..mcp.server import CurlStudioMCPServer
from ..storage.command_store import CommandLibraryStore, LLMSettings


if PYQT_AVAILABLE:

    class LLMChatWorker(QThread):
        finished_signal = pyqtSignal(object)

        def __init__(
            self,
            client: LLMClient,
            prompt: str,
            history: List[ChatMessage],
            active_spec: Optional[CurlCommandSpec],
            last_response_summary: str,
        ) -> None:
            super().__init__()
            self.client = client
            self.prompt = prompt
            self.history = list(history)
            self.active_spec = active_spec
            self.last_response_summary = last_response_summary

        def run(self) -> None:
            reply = self.client.send_chat(
                user_prompt=self.prompt,
                history=self.history,
                active_spec=self.active_spec,
                last_response_summary=self.last_response_summary,
            )
            self.finished_signal.emit(reply)


    class LLMChatWidget(QWidget):
        """Interactive AI Assistant & MCP Tool Chat Panel for Local & External LLMs."""

        def __init__(
            self,
            store: CommandLibraryStore,
            mcp_server: CurlStudioMCPServer,
            get_active_spec: Callable[[], CurlCommandSpec],
            get_last_response_summary: Callable[[], str],
            apply_curl_to_builder: Callable[[str], None],
        ) -> None:
            super().__init__()
            self.store = store
            self.mcp_server = mcp_server
            self.get_active_spec = get_active_spec
            self.get_last_response_summary = get_last_response_summary
            self.apply_curl_to_builder = apply_curl_to_builder

            self.settings: LLMSettings = self.store.load_llm_settings()
            self.history: List[ChatMessage] = []
            self.last_suggested_curl: Optional[str] = None

            self._build_ui()
            self._load_settings_into_ui()

        def _build_ui(self) -> None:
            layout = QVBoxLayout(self)
            layout.setContentsMargins(6, 6, 6, 6)
            layout.setSpacing(8)

            # 1. Provider & Endpoint Settings Group
            cfg_group = QGroupBox("LLM Provider & MCP Integration Settings (Local Ollama / External API)")
            cfg_grid = QGridLayout(cfg_group)

            cfg_grid.addWidget(QLabel("Provider:"), 0, 0)
            self.provider_combo = QComboBox()
            for key, meta in PROVIDER_PRESETS.items():
                self.provider_combo.addItem(meta["label"], key)
            self.provider_combo.currentIndexChanged.connect(self.on_provider_changed)
            cfg_grid.addWidget(self.provider_combo, 0, 1, 1, 3)

            cfg_grid.addWidget(QLabel("Endpoint URL:"), 1, 0)
            self.url_edit = QLineEdit()
            self.url_edit.setFont(QFont("Consolas", 9))
            cfg_grid.addWidget(self.url_edit, 1, 1, 1, 3)

            cfg_grid.addWidget(QLabel("Model Name:"), 2, 0)
            self.model_edit = QLineEdit()
            self.model_edit.setFont(QFont("Consolas", 9))
            cfg_grid.addWidget(self.model_edit, 2, 1)

            cfg_grid.addWidget(QLabel("API Key (External):"), 2, 2)
            self.key_edit = QLineEdit()
            self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self.key_edit.setPlaceholderText("Leave empty for Local Ollama / LM Studio")
            cfg_grid.addWidget(self.key_edit, 2, 3)

            bottom_cfg = QHBoxLayout()
            self.mcp_cb = QCheckBox("Auto-Call Local MCP Server Tools (parse, diagnose, flags, library)")
            self.mcp_cb.setChecked(True)
            btn_save_cfg = QPushButton("Save LLM Config")
            btn_save_cfg.clicked.connect(self.on_save_settings)
            bottom_cfg.addWidget(self.mcp_cb)
            bottom_cfg.addStretch()
            bottom_cfg.addWidget(btn_save_cfg)
            cfg_grid.addLayout(bottom_cfg, 3, 0, 1, 4)

            layout.addWidget(cfg_group)

            # 2. Quick Prompt Buttons
            quick_row = QHBoxLayout()
            btn_q1 = QPushButton("Explain Builder Command for Trainee")
            btn_q1.clicked.connect(
                lambda: self.send_quick_prompt("Explain the current builder curl command step-by-step for a trainee.")
            )
            btn_q2 = QPushButton("Check Quotes & URL Syntax")
            btn_q2.clicked.connect(
                lambda: self.send_quick_prompt(
                    'Diagnose curl -X POST "http:sdfble" -H "Content-Type: application/json" -d "{"product_id": "101", "quantity": 1, "price": 0.01}"'
                )
            )
            btn_q3 = QPushButton("SSL & Redirect Flags (-k, -L, -v)")
            btn_q3.clicked.connect(
                lambda: self.send_quick_prompt("Explain the SSL and redirect flags (-k, -L, -v) with examples.")
            )
            quick_row.addWidget(btn_q1)
            quick_row.addWidget(btn_q2)
            quick_row.addWidget(btn_q3)
            layout.addLayout(quick_row)

            # 3. Chat Transcript View
            self.chat_browser = QTextBrowser()
            self.chat_browser.setOpenExternalLinks(False)
            layout.addWidget(self.chat_browser, 1)

            # 4. Suggested Command Bar (Apply to Visual Builder)
            apply_row = QHBoxLayout()
            self.suggested_lbl = QLabel("MCP / LLM Suggested Command: (None yet)")
            self.suggested_lbl.setStyleSheet("color: #5c6470; font-size: 12px;")
            self.btn_apply_suggested = QPushButton("Load Suggested cURL into Visual Builder")
            self.btn_apply_suggested.setEnabled(False)
            self.btn_apply_suggested.clicked.connect(self.on_apply_suggested)
            apply_row.addWidget(self.suggested_lbl, 1)
            apply_row.addWidget(self.btn_apply_suggested)
            layout.addLayout(apply_row)

            # 5. User Prompt Input Bar
            input_row = QHBoxLayout()
            self.prompt_edit = QLineEdit()
            self.prompt_edit.setPlaceholderText(
                "Ask Local LLM / External API or paste a broken curl command..."
            )
            self.prompt_edit.returnPressed.connect(self.on_send_clicked)

            self.btn_send = QPushButton("Send to LLM")
            self.btn_send.setObjectName("primaryBtn")
            self.btn_send.clicked.connect(self.on_send_clicked)

            btn_clear = QPushButton("Clear")
            btn_clear.clicked.connect(self.on_clear_chat)

            input_row.addWidget(self.prompt_edit, 1)
            input_row.addWidget(self.btn_send)
            input_row.addWidget(btn_clear)
            layout.addLayout(input_row)

            self._append_system_welcome()

        def _append_system_welcome(self) -> None:
            self.chat_browser.setHtml(
                """
                <div style="font-family:'Segoe UI',sans-serif; font-size:13px; color:#11141a; line-height:1.5;">
                  <div style="background:#e8eefc; color:#223c9e; padding:10px 12px; border-radius:6px; margin-bottom:10px;">
                    <b>LLM + MCP Assistant Ready</b><br>
                    Connect to a <b>Local LLM</b> (Ollama on <code>localhost:11434</code>, LM Studio on <code>localhost:1234</code>),
                    an <b>External LLM API</b> (OpenAI, Anthropic, Groq, OpenRouter), or use the <b>Built-in Offline MCP Coach</b>.
                  </div>
                </div>
                """
            )

        def _load_settings_into_ui(self) -> None:
            idx = self.provider_combo.findData(self.settings.provider)
            self.provider_combo.blockSignals(True)
            if idx >= 0:
                self.provider_combo.setCurrentIndex(idx)
            self.provider_combo.blockSignals(False)
            self.url_edit.setText(self.settings.base_url)
            self.model_edit.setText(self.settings.model_name)
            self.key_edit.setText(self.settings.api_key)
            self.mcp_cb.setChecked(self.settings.enable_mcp_tools)

        def on_provider_changed(self) -> None:
            prov_key = self.provider_combo.currentData()
            meta = PROVIDER_PRESETS.get(prov_key, PROVIDER_PRESETS["ollama"])
            self.url_edit.setText(meta["base_url"])
            self.model_edit.setText(meta["default_model"])
            self.on_save_settings()

        def on_save_settings(self) -> None:
            self.settings = LLMSettings(
                provider=self.provider_combo.currentData(),
                base_url=self.url_edit.text().strip(),
                model_name=self.model_edit.text().strip(),
                api_key=self.key_edit.text().strip(),
                enable_mcp_tools=self.mcp_cb.isChecked(),
            )
            self.store.save_llm_settings(self.settings)

        def send_quick_prompt(self, text: str) -> None:
            self.prompt_edit.setText(text)
            self.on_send_clicked()

        def on_send_clicked(self) -> None:
            prompt = self.prompt_edit.text().strip()
            if not prompt:
                return
            self.prompt_edit.clear()
            self.on_save_settings()

            self._append_bubble("You", prompt, "#f1f3f6", "#11141a")
            self.btn_send.setEnabled(False)
            self.btn_send.setText("Thinking...")

            client = LLMClient(self.settings, self.mcp_server)
            self.worker = LLMChatWorker(
                client=client,
                prompt=prompt,
                history=self.history,
                active_spec=self.get_active_spec(),
                last_response_summary=self.get_last_response_summary(),
            )
            self.worker.finished_signal.connect(lambda reply, up=prompt: self.on_reply_received(up, reply))
            self.worker.start()

        def on_reply_received(self, user_prompt: str, reply: LLMReply) -> None:
            self.btn_send.setEnabled(True)
            self.btn_send.setText("Send to LLM")

            self.history.append(ChatMessage("user", user_prompt))
            self.history.append(ChatMessage("assistant", reply.text))

            header = f"Assistant [{reply.provider_used}]"
            if reply.mcp_tool_called:
                header += f" • MCP Tool Called: {reply.mcp_tool_called}()"

            formatted_html = self._markdown_to_simple_html(reply.text)
            self._append_bubble(header, formatted_html, "#ffffff", "#11141a", is_html=True)

            if reply.suggested_curl:
                self.last_suggested_curl = reply.suggested_curl
                short_preview = (
                    reply.suggested_curl[:75] + "..."
                    if len(reply.suggested_curl) > 75
                    else reply.suggested_curl
                )
                self.suggested_lbl.setText(f"Suggested: {short_preview}")
                self.btn_apply_suggested.setEnabled(True)

        def on_apply_suggested(self) -> None:
            if self.last_suggested_curl:
                self.apply_curl_to_builder(self.last_suggested_curl)

        def on_clear_chat(self) -> None:
            self.history.clear()
            self._append_system_welcome()

        def _append_bubble(
            self, sender: str, body: str, bg: str, fg: str, is_html: bool = False
        ) -> None:
            safe_body = body if is_html else (
                body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
            )
            block = f"""
            <div style="background:{bg}; color:{fg}; border:1px solid #dfe3eb; border-radius:6px; padding:10px 12px; margin-bottom:10px;">
              <div style="font-size:11px; font-weight:bold; color:#3559e6; margin-bottom:4px;">{sender}</div>
              <div style="font-size:13px; line-height:1.5;">{safe_body}</div>
            </div>
            """
            self.chat_browser.append(block)

        @staticmethod
        def _markdown_to_simple_html(md: str) -> str:
            import re as _re
            escaped = md.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            # Code blocks
            escaped = _re.sub(
                r"```[a-zA-Z]*\n([\s\S]*?)```",
                r'<pre style="background:#12151e; color:#eef1f7; padding:8px 10px; border-radius:5px; font-family:Consolas,monospace; font-size:12px;">\1</pre>',
                escaped,
            )
            # Inline code
            escaped = _re.sub(
                r"`([^`]+)`",
                r'<code style="background:#e9ecf1; padding:1px 5px; border-radius:3px; font-family:Consolas,monospace;">\1</code>',
                escaped,
            )
            # Bold
            escaped = _re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", escaped)
            # Headings
            escaped = _re.sub(r"^###\s+(.+)$", r"<h4 style='margin:6px 0 4px 0; color:#223c9e;'>\1</h4>", escaped, flags=_re.MULTILINE)
            return escaped.replace("\n", "<br>")
