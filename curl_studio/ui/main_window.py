"""
Main Desktop Window for cURL Interactive Studio & Trainee Guide (PyQt6)
=======================================================================
Combines:
  - Raw cURL Importer & Trainee Quote Doctor (top bar)
  - Saved Everyday Commands SQLite Sidebar (left pane)
  - Tab 1: Visual Request Builder & Multi-Shell Runner
  - Tab 2: Common Flags Encyclopedia (18 flags)
  - Tab 3: Trainee Pitfalls & Classroom Drills
  - Tab 4 / Dock: LLM Chat & MCP Server Console (Local Ollama / LM Studio + External APIs)
"""

from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from PyQt6.QtCore import Qt, QThread, pyqtSignal
    from PyQt6.QtGui import QColor, QFont, QGuiApplication
    from PyQt6.QtWidgets import (
        QAbstractItemView,
        QCheckBox,
        QComboBox,
        QDockWidget,
        QFileDialog,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QHeaderView,
        QInputDialog,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QMainWindow,
        QMessageBox,
        QPlainTextEdit,
        QPushButton,
        QScrollArea,
        QSplitter,
        QStatusBar,
        QTableWidget,
        QTableWidgetItem,
        QTabWidget,
        QTextBrowser,
        QVBoxLayout,
        QWidget,
    )
    PYQT_AVAILABLE = True
except ImportError:
    PYQT_AVAILABLE = False

from ..core.flags_db import CURL_FLAGS_DB, CURL_FLAGS_MAP
from ..core.formatter import format_command_for_shell, generate_anatomy_html
from ..core.models import CurlCommandSpec, ExecutionResult, HeaderItem
from ..core.parser import diagnose_raw_curl, parse_raw_curl_command
from ..core.runner import execute_curl_spec
from ..mcp.server import CurlStudioMCPServer, MCP_TOOLS_SCHEMA
from ..storage.command_store import CommandLibraryStore

if PYQT_AVAILABLE:
    from .llm_chat_widget import LLMChatWidget

    class RequestWorker(QThread):
        finished_signal = pyqtSignal(object)

        def __init__(self, spec: CurlCommandSpec, mode: str) -> None:
            super().__init__()
            self.spec = spec
            self.mode = mode

        def run(self) -> None:
            res = execute_curl_spec(self.spec, self.mode)
            self.finished_signal.emit(res)


    class CurlStudioMainWindow(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle(
                "cURL Interactive Studio, MCP Server & LLM Assistant — Desktop Suite v2.0"
            )
            self.resize(1480, 920)

            self.store = CommandLibraryStore()
            self.mcp_server = CurlStudioMCPServer(self.store)
            self.current_row_id: Optional[int] = None
            self.current_spec = CurlCommandSpec()
            self.current_shell_fmt = "bash"
            self.last_result: Optional[ExecutionResult] = None
            self._syncing_json = False

            self._apply_stylesheet()
            self._build_ui()
            self._reload_saved_list(select_first=True)

        def _apply_stylesheet(self) -> None:
            self.setStyleSheet(
                """
                QMainWindow, QWidget {
                    background-color: #f7f8fa;
                    color: #11141a;
                    font-family: "Inter", "Segoe UI", -apple-system, sans-serif;
                    font-size: 13px;
                }
                QGroupBox {
                    background-color: #ffffff;
                    border: 1px solid #dfe3eb;
                    border-radius: 6px;
                    margin-top: 10px;
                    padding-top: 14px;
                    font-weight: 600;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 5px;
                    color: #3559e6;
                }
                QLineEdit, QComboBox, QPlainTextEdit, QTableWidget, QListWidget {
                    background-color: #ffffff;
                    border: 1px solid #cdd2db;
                    border-radius: 5px;
                    padding: 5px 8px;
                }
                QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {
                    border: 1px solid #3559e6;
                }
                QPushButton {
                    background-color: #ffffff;
                    border: 1px solid #cdd2db;
                    border-radius: 5px;
                    padding: 6px 12px;
                    font-weight: 500;
                }
                QPushButton:hover {
                    background-color: #eef1f6;
                }
                QPushButton#primaryBtn {
                    background-color: #3559e6;
                    color: #ffffff;
                    border: 1px solid #3559e6;
                    font-weight: 600;
                }
                QPushButton#primaryBtn:hover {
                    background-color: #2442b8;
                }
                QPushButton#runBtn {
                    background-color: #159a6a;
                    color: #ffffff;
                    border: 1px solid #159a6a;
                    font-weight: 600;
                    padding: 7px 16px;
                }
                QPushButton#runBtn:hover {
                    background-color: #117f57;
                }
                QTabWidget::pane {
                    border: 1px solid #dfe3eb;
                    background: #ffffff;
                    border-radius: 5px;
                }
                QTabBar::tab {
                    background: #e9ecf1;
                    border: 1px solid #dfe3eb;
                    padding: 7px 14px;
                    margin-right: 4px;
                    border-top-left-radius: 5px;
                    border-top-right-radius: 5px;
                }
                QTabBar::tab:selected {
                    background: #ffffff;
                    color: #3559e6;
                    font-weight: 600;
                }
                """
            )

        def _build_ui(self) -> None:
            central = QWidget()
            self.setCentralWidget(central)
            root_layout = QVBoxLayout(central)
            root_layout.setContentsMargins(10, 8, 10, 8)
            root_layout.setSpacing(8)

            # --- TOP BAR: RAW CURL IMPORTER & QUOTE DOCTOR ---
            import_group = QGroupBox("Paste Any Raw cURL Command (Auto-Parses & Fixes Broken Quotes)")
            import_layout = QVBoxLayout(import_group)

            top_row = QHBoxLayout()
            self.raw_curl_input = QLineEdit()
            self.raw_curl_input.setFont(QFont("Consolas", 10))
            self.raw_curl_input.setText(
                'curl -X POST "http:sdfble" -H "Content-Type: application/json" '
                '-d "{"product_id": "101", "quantity": 1, "price": 0.01}"'
            )
            self.raw_curl_input.returnPressed.connect(self.on_parse_raw_clicked)

            btn_parse = QPushButton("Parse into Builder")
            btn_parse.setObjectName("primaryBtn")
            btn_parse.clicked.connect(self.on_parse_raw_clicked)

            btn_autofix = QPushButton("Auto-Fix Quotes & URL Scheme")
            btn_autofix.clicked.connect(self.on_autofix_raw_clicked)

            btn_toggle_llm = QPushButton("Toggle AI / LLM Chat Dock")
            btn_toggle_llm.clicked.connect(self.on_toggle_llm_dock)

            top_row.addWidget(self.raw_curl_input, 1)
            top_row.addWidget(btn_parse)
            top_row.addWidget(btn_autofix)
            top_row.addWidget(btn_toggle_llm)
            import_layout.addLayout(top_row)

            self.doctor_label = QLabel()
            self.doctor_label.setWordWrap(True)
            import_layout.addWidget(self.doctor_label)
            root_layout.addWidget(import_group)

            # --- MAIN SPLITTER: LEFT SIDEBAR + CENTER WORKSPACE ---
            main_splitter = QSplitter(Qt.Orientation.Horizontal)

            # Left Sidebar: Saved Everyday Commands
            sidebar_widget = QGroupBox("Saved Everyday Commands")
            sidebar_layout = QVBoxLayout(sidebar_widget)

            self.saved_list = QListWidget()
            self.saved_list.currentRowChanged.connect(self.on_saved_command_selected)
            sidebar_layout.addWidget(self.saved_list, 1)

            side_btn_row1 = QHBoxLayout()
            btn_save_new = QPushButton("+ Save New")
            btn_save_new.setObjectName("primaryBtn")
            btn_save_new.clicked.connect(self.on_save_new_command)

            btn_update_cur = QPushButton("Update Selected")
            btn_update_cur.clicked.connect(self.on_update_selected_command)
            side_btn_row1.addWidget(btn_save_new)
            side_btn_row1.addWidget(btn_update_cur)
            sidebar_layout.addLayout(side_btn_row1)

            side_btn_row2 = QHBoxLayout()
            btn_delete = QPushButton("Delete")
            btn_delete.clicked.connect(self.on_delete_selected_command)
            btn_export = QPushButton("Export JSON")
            btn_export.clicked.connect(self.on_export_json)
            btn_import = QPushButton("Import JSON")
            btn_import.clicked.connect(self.on_import_json)
            side_btn_row2.addWidget(btn_delete)
            side_btn_row2.addWidget(btn_export)
            side_btn_row2.addWidget(btn_import)
            sidebar_layout.addLayout(side_btn_row2)

            main_splitter.addWidget(sidebar_widget)

            # Center Main Tabs
            self.main_tabs = QTabWidget()
            self.main_tabs.addTab(self._build_workbench_tab(), "1. Visual Request Builder & Runner")
            self.main_tabs.addTab(self._build_encyclopedia_tab(), "2. Common Flags Encyclopedia (18 Flags)")
            self.main_tabs.addTab(self._build_mcp_inspector_tab(), "3. MCP Server & Tools Console")
            self.main_tabs.addTab(self._build_trainee_drills_tab(), "4. Trainee Pitfalls & Drills")

            main_splitter.addWidget(self.main_tabs)
            main_splitter.setSizes([250, 820])
            root_layout.addWidget(main_splitter, 1)

            # --- RIGHT DOCK: INTEGRATED LLM CHAT WINDOW (LOCAL + EXTERNAL API) ---
            self.llm_dock = QDockWidget("LLM Assistant & Trainee Coach (Local Ollama / External API + MCP)", self)
            self.llm_dock.setAllowedAreas(
                Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.LeftDockWidgetArea
            )
            self.llm_chat_widget = LLMChatWidget(
                store=self.store,
                mcp_server=self.mcp_server,
                get_active_spec=lambda: self.current_spec,
                get_last_response_summary=self._get_last_response_summary,
                apply_curl_to_builder=self._apply_curl_from_llm,
            )
            self.llm_dock.setWidget(self.llm_chat_widget)
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.llm_dock)

            self.status_bar = QStatusBar()
            self.setStatusBar(self.status_bar)
            self._update_doctor_banner(self.raw_curl_input.text())

        def on_toggle_llm_dock(self) -> None:
            self.llm_dock.setVisible(not self.llm_dock.isVisible())

        def _get_last_response_summary(self) -> str:
            if not self.last_result:
                return ""
            return f"{self.last_result.status_line} ({self.last_result.elapsed_ms} ms)\n{self.last_result.pretty_body[:400]}"

        def _apply_curl_from_llm(self, raw_cmd: str) -> None:
            self.raw_curl_input.setText(raw_cmd)
            self.on_parse_raw_clicked()
            self.main_tabs.setCurrentIndex(0)

        def _build_workbench_tab(self) -> QWidget:
            tab = QWidget()
            layout = QVBoxLayout(tab)
            horiz_splitter = QSplitter(Qt.Orientation.Horizontal)

            # Left Pane: Builder Controls
            left_pane = QWidget()
            left_layout = QVBoxLayout(left_pane)
            left_layout.setContentsMargins(4, 4, 4, 4)

            endpoint_group = QGroupBox("Endpoint & Command Label")
            ep_grid = QGridLayout(endpoint_group)

            ep_grid.addWidget(QLabel("Label:"), 0, 0)
            self.name_edit = QLineEdit()
            self.name_edit.textChanged.connect(self.on_builder_changed)
            ep_grid.addWidget(self.name_edit, 0, 1, 1, 3)

            ep_grid.addWidget(QLabel("Method (-X):"), 1, 0)
            self.method_combo = QComboBox()
            self.method_combo.addItems(["POST", "GET", "PUT", "PATCH", "DELETE", "HEAD"])
            self.method_combo.currentTextChanged.connect(self.on_builder_changed)
            ep_grid.addWidget(self.method_combo, 1, 1)

            ep_grid.addWidget(QLabel("URL:"), 1, 2)
            self.url_edit = QLineEdit()
            self.url_edit.setFont(QFont("Consolas", 10))
            self.url_edit.textChanged.connect(self.on_builder_changed)
            ep_grid.addWidget(self.url_edit, 1, 3)

            left_layout.addWidget(endpoint_group)

            self.builder_subtabs = QTabWidget()

            # Subtab 1: Payload (-d)
            payload_widget = QWidget()
            payload_layout = QVBoxLayout(payload_widget)

            pay_top = QHBoxLayout()
            self.json_status_lbl = QLabel("Valid JSON")
            self.json_status_lbl.setStyleSheet("color: #159a6a; font-weight: bold;")
            btn_add_json_key = QPushButton("+ Add JSON Key")
            btn_add_json_key.clicked.connect(self.on_add_json_key_row)
            btn_pretty_json = QPushButton("Prettify JSON")
            btn_pretty_json.clicked.connect(self.on_prettify_json)
            btn_minify_json = QPushButton("Minify")
            btn_minify_json.clicked.connect(self.on_minify_json)

            pay_top.addWidget(QLabel("Visual JSON Field Editor (No quotes needed):"))
            pay_top.addStretch()
            pay_top.addWidget(self.json_status_lbl)
            pay_top.addWidget(btn_add_json_key)
            pay_top.addWidget(btn_pretty_json)
            pay_top.addWidget(btn_minify_json)
            payload_layout.addLayout(pay_top)

            self.json_table = QTableWidget(0, 4)
            self.json_table.setHorizontalHeaderLabels(["JSON Key", "Type", "Value", ""])
            self.json_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            self.json_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
            self.json_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
            self.json_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
            self.json_table.cellChanged.connect(self.on_json_table_cell_changed)
            payload_layout.addWidget(self.json_table, 1)

            payload_layout.addWidget(QLabel("Raw Payload (-d / --data):"))
            self.body_edit = QPlainTextEdit()
            self.body_edit.setFont(QFont("Consolas", 10))
            self.body_edit.setMaximumHeight(110)
            self.body_edit.textChanged.connect(self.on_raw_body_text_changed)
            payload_layout.addWidget(self.body_edit)

            self.builder_subtabs.addTab(payload_widget, "Payload Body (-d)")

            # Subtab 2: Headers (-H)
            headers_widget = QWidget()
            headers_layout = QVBoxLayout(headers_widget)
            hdr_btn_row = QHBoxLayout()
            btn_add_hdr = QPushButton("+ Add Header Row")
            btn_add_hdr.clicked.connect(lambda: self.add_header_row("", "", True))
            btn_preset_json = QPushButton("+ Content-Type: application/json")
            btn_preset_json.clicked.connect(
                lambda: self.add_or_update_header("Content-Type", "application/json")
            )
            btn_preset_auth = QPushButton("+ Bearer Token Header")
            btn_preset_auth.clicked.connect(
                lambda: self.add_or_update_header("Authorization", "Bearer YOUR_TOKEN")
            )
            hdr_btn_row.addWidget(btn_add_hdr)
            hdr_btn_row.addWidget(btn_preset_json)
            hdr_btn_row.addWidget(btn_preset_auth)
            hdr_btn_row.addStretch()
            headers_layout.addLayout(hdr_btn_row)

            self.headers_table = QTableWidget(0, 4)
            self.headers_table.setHorizontalHeaderLabels(["On", "Header Key (-H)", "Header Value", ""])
            self.headers_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            self.headers_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            self.headers_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
            self.headers_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
            self.headers_table.cellChanged.connect(self.on_headers_table_changed)
            headers_layout.addWidget(self.headers_table, 1)

            self.builder_subtabs.addTab(headers_widget, "HTTP Headers (-H)")

            # Subtab 3: Common Flags Checkboxes
            flags_scroll = QScrollArea()
            flags_scroll.setWidgetResizable(True)
            flags_container = QWidget()
            flags_grid = QGridLayout(flags_container)

            self.flag_checkboxes: Dict[str, QCheckBox] = {}
            self.flag_arg_inputs: Dict[str, QLineEdit] = {}

            row_idx = 0
            for f in CURL_FLAGS_DB:
                if not f.toggleable:
                    continue
                cb = QCheckBox(f"{f.short} ({f.long.split()[0]}) — {f.summary}")
                cb.setToolTip(f"{f.detail}\n\nTrainee Tip: {f.trainee_tip}")
                cb.stateChanged.connect(self.on_flags_ui_changed)
                self.flag_checkboxes[f.flag_id] = cb
                flags_grid.addWidget(cb, row_idx, 0)

                if f.has_arg:
                    arg_edit = QLineEdit(f.default_arg)
                    arg_edit.setFont(QFont("Consolas", 10))
                    arg_edit.setMaximumWidth(200)
                    arg_edit.textChanged.connect(self.on_flags_ui_changed)
                    self.flag_arg_inputs[f.flag_id] = arg_edit
                    flags_grid.addWidget(arg_edit, row_idx, 1)
                row_idx += 1

            flags_grid.setRowStretch(row_idx, 1)
            flags_scroll.setWidget(flags_container)
            self.builder_subtabs.addTab(flags_scroll, "Common Flags (-i, -v, -L, -k, -u...)")

            left_layout.addWidget(self.builder_subtabs, 1)

            anatomy_group = QGroupBox("Trainee Visual Command Breakdown (Explains Every Active Flag)")
            anatomy_layout = QVBoxLayout(anatomy_group)
            self.anatomy_browser = QTextBrowser()
            self.anatomy_browser.setMinimumHeight(175)
            anatomy_layout.addWidget(self.anatomy_browser)
            left_layout.addWidget(anatomy_group)

            horiz_splitter.addWidget(left_pane)

            # Right Pane: Generated Command & Response Inspector
            right_pane = QWidget()
            right_layout = QVBoxLayout(right_pane)
            right_layout.setContentsMargins(4, 4, 4, 4)

            gen_group = QGroupBox("Generated Command (Properly Quoted & Escaped)")
            gen_layout = QVBoxLayout(gen_group)

            shell_bar = QHBoxLayout()
            shell_bar.addWidget(QLabel("Target Format:"))
            self.shell_combo = QComboBox()
            self.shell_combo.addItem("Bash / Zsh (Multiline)", "bash")
            self.shell_combo.addItem("Bash / Zsh (One-Liner)", "oneline")
            self.shell_combo.addItem("Windows CMD (Escaped Quotes)", "cmd")
            self.shell_combo.addItem("Windows PowerShell", "ps")
            self.shell_combo.addItem("Python requests Code", "python")
            self.shell_combo.currentIndexChanged.connect(self.on_shell_format_changed)
            shell_bar.addWidget(self.shell_combo)
            shell_bar.addStretch()

            btn_copy_cmd = QPushButton("Copy Command")
            btn_copy_cmd.clicked.connect(self.on_copy_generated_command)
            shell_bar.addWidget(btn_copy_cmd)
            gen_layout.addLayout(shell_bar)

            self.generated_cmd_edit = QPlainTextEdit()
            self.generated_cmd_edit.setReadOnly(True)
            self.generated_cmd_edit.setFont(QFont("Consolas", 10))
            self.generated_cmd_edit.setStyleSheet(
                "background-color: #12151e; color: #eef1f7; border-radius: 6px; padding: 8px;"
            )
            self.generated_cmd_edit.setMaximumHeight(140)
            gen_layout.addWidget(self.generated_cmd_edit)
            right_layout.addWidget(gen_group)

            resp_group = QGroupBox("HTTP Response Inspector")
            resp_layout = QVBoxLayout(resp_group)

            run_bar = QHBoxLayout()
            run_bar.addWidget(QLabel("Run Mode:"))
            self.exec_mode_combo = QComboBox()
            self.exec_mode_combo.addItem("Smart Mode (Real System cURL + Trainee Fallback)", "auto")
            self.exec_mode_combo.addItem("Real System cURL Only (Strict)", "real_curl")
            self.exec_mode_combo.addItem("Trainee Simulator: 201 Created / 200 OK", "sim_200")
            self.exec_mode_combo.addItem("Trainee Simulator: 400 Bad JSON Error", "sim_400")
            self.exec_mode_combo.addItem("Trainee Simulator: 401 Unauthorized", "sim_401")
            self.exec_mode_combo.addItem("Trainee Simulator: 500 Server Error", "sim_500")
            run_bar.addWidget(self.exec_mode_combo, 1)

            self.btn_run = QPushButton("Send Request / Run cURL")
            self.btn_run.setObjectName("runBtn")
            self.btn_run.clicked.connect(self.on_execute_clicked)
            run_bar.addWidget(self.btn_run)
            resp_layout.addLayout(run_bar)

            status_row = QHBoxLayout()
            self.resp_status_badge = QLabel("Ready to Run")
            self.resp_status_badge.setStyleSheet(
                "background-color: #e8eefc; color: #223c9e; padding: 4px 10px; "
                "border-radius: 4px; font-family: Consolas, monospace; font-weight: bold;"
            )
            self.resp_time_lbl = QLabel("Latency: —")
            self.resp_mode_lbl = QLabel("")
            self.resp_mode_lbl.setStyleSheet("color: #5c6470; font-size: 12px;")
            status_row.addWidget(self.resp_status_badge)
            status_row.addWidget(self.resp_time_lbl)
            status_row.addStretch()
            status_row.addWidget(self.resp_mode_lbl)
            resp_layout.addLayout(status_row)

            self.resp_tabs = QTabWidget()
            self.resp_pretty_view = QPlainTextEdit()
            self.resp_pretty_view.setReadOnly(True)
            self.resp_pretty_view.setFont(QFont("Consolas", 10))

            self.resp_headers_view = QPlainTextEdit()
            self.resp_headers_view.setReadOnly(True)
            self.resp_headers_view.setFont(QFont("Consolas", 10))

            self.resp_verbose_view = QPlainTextEdit()
            self.resp_verbose_view.setReadOnly(True)
            self.resp_verbose_view.setFont(QFont("Consolas", 10))

            self.resp_tabs.addTab(self.resp_pretty_view, "Pretty Response Body")
            self.resp_tabs.addTab(self.resp_headers_view, "Response Headers (-i)")
            self.resp_tabs.addTab(self.resp_verbose_view, "Verbose Handshake Trace (-v)")

            resp_layout.addWidget(self.resp_tabs, 1)
            right_layout.addWidget(resp_group, 1)

            horiz_splitter.addWidget(right_pane)
            horiz_splitter.setSizes([460, 420])
            layout.addWidget(horiz_splitter)
            return tab

        def _build_encyclopedia_tab(self) -> QWidget:
            tab = QWidget()
            layout = QVBoxLayout(tab)

            filter_row = QHBoxLayout()
            filter_row.addWidget(QLabel("Search Flag or Keyword:"))
            self.flag_search_edit = QLineEdit()
            self.flag_search_edit.setPlaceholderText("Search -X, -H, -d, -L, -k, cookie, proxy, timeout...")
            self.flag_search_edit.textChanged.connect(self._populate_encyclopedia_table)
            filter_row.addWidget(self.flag_search_edit, 1)

            filter_row.addWidget(QLabel("Category:"))
            self.flag_cat_combo = QComboBox()
            self.flag_cat_combo.addItems(
                [
                    "All Categories",
                    "Method & Headers",
                    "Payload & Upload",
                    "Auth & Security",
                    "Debugging & Output",
                    "Network & Redirects",
                ]
            )
            self.flag_cat_combo.currentTextChanged.connect(self._populate_encyclopedia_table)
            filter_row.addWidget(self.flag_cat_combo)
            layout.addLayout(filter_row)

            self.enc_table = QTableWidget(0, 6)
            self.enc_table.setHorizontalHeaderLabels(
                ["Flag", "Long Form", "Category", "What It Does", "Example & Trainee Gotcha", "Try in Builder"]
            )
            self.enc_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            self.enc_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
            self.enc_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
            self.enc_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
            self.enc_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
            self.enc_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
            self.enc_table.verticalHeader().setDefaultSectionSize(64)
            self.enc_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            layout.addWidget(self.enc_table, 1)

            self._populate_encyclopedia_table()
            return tab

        def _populate_encyclopedia_table(self) -> None:
            q = self.flag_search_edit.text().strip().lower()
            cat = self.flag_cat_combo.currentText()
            self.enc_table.setRowCount(0)

            for f in CURL_FLAGS_DB:
                if cat != "All Categories" and f.category != cat:
                    continue
                hay = f"{f.short} {f.long} {f.summary} {f.detail} {f.example} {f.trainee_tip}".lower()
                if q and q not in hay:
                    continue

                r = self.enc_table.rowCount()
                self.enc_table.insertRow(r)

                item_short = QTableWidgetItem(f.short)
                item_short.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
                item_short.setForeground(QColor("#3559e6"))
                self.enc_table.setItem(r, 0, item_short)

                item_long = QTableWidgetItem(f.long)
                item_long.setFont(QFont("Consolas", 9))
                self.enc_table.setItem(r, 1, item_long)

                self.enc_table.setItem(r, 2, QTableWidgetItem(f.category))
                self.enc_table.setItem(r, 3, QTableWidgetItem(f"{f.summary}\n{f.detail}"))
                self.enc_table.setItem(
                    r, 4, QTableWidgetItem(f"Ex: {f.example}\nTip: {f.trainee_tip}")
                )

                btn_try = QPushButton("Toggle in Builder")
                btn_try.clicked.connect(lambda checked=False, fid=f.flag_id: self.on_try_flag_from_encyclopedia(fid))
                self.enc_table.setCellWidget(r, 5, btn_try)

        def _build_mcp_inspector_tab(self) -> QWidget:
            """Interactive console to test the built-in MCP Server tools and copy Claude/Cursor config."""
            tab = QWidget()
            layout = QVBoxLayout(tab)

            info_group = QGroupBox("Model Context Protocol (MCP) Server Configuration (Stdio & HTTP)")
            info_layout = QVBoxLayout(info_group)
            info_browser = QTextBrowser()
            info_browser.setMaximumHeight(165)
            info_browser.setHtml(
                """
                <div style="font-family:'Segoe UI',sans-serif; font-size:13px;">
                  <b>External MCP Client Configuration (Claude Desktop / Cursor / VS Code Cline):</b>
                  <pre style="background:#12151e; color:#eef1f7; padding:8px; border-radius:5px; font-family:Consolas,monospace; font-size:12px;">{
  "mcpServers": {
    "curl-studio": {
      "command": "python",
      "args": ["-m", "curl_studio.mcp.server"]
    }
  }
}</pre>
                  <span>Or run HTTP JSON-RPC server: <code>python -m curl_studio.mcp.server --http --port 8765</code></span>
                </div>
                """
            )
            info_layout.addWidget(info_browser)
            layout.addWidget(info_group)

            tester_group = QGroupBox("Live MCP Tool Tester (In-Process JSON-RPC 2.0 Dispatch)")
            tester_layout = QVBoxLayout(tester_group)

            tool_row = QHBoxLayout()
            tool_row.addWidget(QLabel("MCP Tool:"))
            self.mcp_tool_combo = QComboBox()
            for t in MCP_TOOLS_SCHEMA:
                self.mcp_tool_combo.addItem(f"{t['name']} — {t['description'][:65]}...", t["name"])
            self.mcp_tool_combo.currentIndexChanged.connect(self._on_mcp_tool_selected)
            tool_row.addWidget(self.mcp_tool_combo, 1)

            btn_call_mcp = QPushButton("Invoke MCP Tool (tools/call)")
            btn_call_mcp.setObjectName("primaryBtn")
            btn_call_mcp.clicked.connect(self.on_invoke_mcp_tool)
            tool_row.addWidget(btn_call_mcp)
            tester_layout.addLayout(tool_row)

            tester_layout.addWidget(QLabel("Tool Arguments (JSON):"))
            self.mcp_args_edit = QPlainTextEdit()
            self.mcp_args_edit.setFont(QFont("Consolas", 10))
            self.mcp_args_edit.setMaximumHeight(95)
            tester_layout.addWidget(self.mcp_args_edit)

            tester_layout.addWidget(QLabel("MCP JSON-RPC 2.0 Response:"))
            self.mcp_output_edit = QPlainTextEdit()
            self.mcp_output_edit.setReadOnly(True)
            self.mcp_output_edit.setFont(QFont("Consolas", 10))
            tester_layout.addWidget(self.mcp_output_edit, 1)

            layout.addWidget(tester_group, 1)
            self._on_mcp_tool_selected()
            return tab

        def _on_mcp_tool_selected(self) -> None:
            tool_name = self.mcp_tool_combo.currentData()
            sample_args: Dict[str, Any] = {}
            if tool_name == "parse_and_diagnose_curl":
                sample_args = {
                    "raw_command": 'curl -X POST "http:sdfble" -H "Content-Type: application/json" -d "{"product_id": "101", "quantity": 1, "price": 0.01}"',
                    "auto_fix_url": True,
                }
            elif tool_name == "build_curl_command":
                sample_args = {
                    "method": "POST",
                    "url": "http://localhost:8000/api/orders",
                    "headers": {"Content-Type": "application/json"},
                    "body": '{"product_id": "101", "quantity": 1, "price": 0.01}',
                    "flags": ["-i", "-v"],
                }
            elif tool_name == "execute_curl_request":
                sample_args = {
                    "raw_command": 'curl -X POST "http://sdfble" -H "Content-Type: application/json" -d \'{"product_id": "101", "quantity": 1, "price": 0.01}\'',
                    "execution_mode": "auto",
                }
            elif tool_name == "explain_curl_flags":
                sample_args = {"query": "-k", "category": "ALL"}
            elif tool_name == "list_saved_commands":
                sample_args = {}
            elif tool_name == "save_custom_command":
                sample_args = {
                    "name": "MCP Saved Order Test",
                    "raw_command": 'curl -X POST "http://localhost:8000/orders" -H "Content-Type: application/json" -d \'{"product_id": "101"}\'',
                }
            self.mcp_args_edit.setPlainText(json.dumps(sample_args, indent=2))

        def on_invoke_mcp_tool(self) -> None:
            tool_name = self.mcp_tool_combo.currentData()
            try:
                args = json.loads(self.mcp_args_edit.toPlainText() or "{}")
                rpc_req = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": args},
                }
                rpc_resp = self.mcp_server.handle_jsonrpc_request(rpc_req)
                self.mcp_output_edit.setPlainText(json.dumps(rpc_resp, indent=2))
                if tool_name == "save_custom_command":
                    self._reload_saved_list(select_first=False)
            except Exception as exc:
                self.mcp_output_edit.setPlainText(f"Error invoking MCP tool: {exc}")

        def _build_trainee_drills_tab(self) -> QWidget:
            tab = QWidget()
            layout = QVBoxLayout(tab)
            browser = QTextBrowser()
            browser.setHtml(
                """
                <div style="font-family: 'Segoe UI', sans-serif; padding: 12px; line-height: 1.6;">
                  <h2 style="color:#11141a; margin-top:0;">Trainee Onboarding Guide: Top 4 cURL Pitfalls &amp; Fixes</h2>
                  <div style="background:#ffffff; border:1px solid #dfe3eb; border-radius:6px; padding:14px; margin-bottom:14px;">
                    <h3 style="color:#3559e6; margin-top:0;">1. The Nested Double-Quote Trap</h3>
                    <p><b>Broken Command:</b> <code>curl -X POST "http:sdfble" -H "Content-Type: application/json" -d "{"product_id": "101", "quantity": 1, "price": 0.01}"</code></p>
                    <p><b>Why it fails:</b> In Bash/Zsh, outer double quotes pair up with the quote right before <code>product_id</code>, stripping inner quotes and sending invalid JSON <code>{product_id: 101, ...}</code>.</p>
                    <p><b>Fix:</b> Wrap JSON payloads in <b>single quotes</b>: <code>-d '{"product_id": "101", "quantity": 1, "price": 0.01}'</code></p>
                  </div>
                  <div style="background:#ffffff; border:1px solid #dfe3eb; border-radius:6px; padding:14px; margin-bottom:14px;">
                    <h3 style="color:#3559e6; margin-top:0;">2. Missing <code>-H "Content-Type: application/json"</code></h3>
                    <p>By default, <code>-d</code> sends <code>application/x-www-form-urlencoded</code>. Always include <code>-H "Content-Type: application/json"</code> when sending JSON payloads.</p>
                  </div>
                  <div style="background:#ffffff; border:1px solid #dfe3eb; border-radius:6px; padding:14px; margin-bottom:14px;">
                    <h3 style="color:#3559e6; margin-top:0;">3. Empty Response on 301/302 Redirects (Use <code>-L</code>)</h3>
                    <p>cURL does not follow HTTP redirects by default. Add <code>-L</code> (<code>--location</code>) to follow <code>Location:</code> headers automatically.</p>
                  </div>
                  <div style="background:#ffffff; border:1px solid #dfe3eb; border-radius:6px; padding:14px;">
                    <h3 style="color:#3559e6; margin-top:0;">4. Internal Lab Fixtures with Self-Signed SSL Certificates (Use <code>-v</code> and <code>-k</code>)</h3>
                    <p>Use <code>-v</code> to inspect the TLS handshake and <code>-k</code> (<code>--insecure</code>) on trusted internal test benches with self-signed certs.</p>
                  </div>
                </div>
                """
            )
            layout.addWidget(browser)
            return tab

        # =================================================================
        # EVENT HANDLERS & SYNCHRONIZATION
        # =================================================================

        def _reload_saved_list(self, select_first: bool = False) -> None:
            self.saved_list.blockSignals(True)
            self.saved_list.clear()
            self._saved_records = self.store.list_commands()
            for row_id, spec in self._saved_records:
                item = QListWidgetItem(f"[{spec.method}] {spec.name}")
                item.setData(Qt.ItemDataRole.UserRole, row_id)
                self.saved_list.addItem(item)
            self.saved_list.blockSignals(False)

            if select_first and self._saved_records:
                self.saved_list.setCurrentRow(0)

        def on_saved_command_selected(self, index: int) -> None:
            if index < 0 or index >= len(self._saved_records):
                return
            row_id, spec = self._saved_records[index]
            self.current_row_id = row_id
            self.load_spec_into_ui(spec)

        def load_spec_into_ui(self, spec: CurlCommandSpec) -> None:
            self._syncing_json = True
            self.current_spec = CurlCommandSpec.from_dict(spec.to_dict())

            self.name_edit.blockSignals(True)
            self.method_combo.blockSignals(True)
            self.url_edit.blockSignals(True)
            self.body_edit.blockSignals(True)

            self.name_edit.setText(self.current_spec.name)
            self.method_combo.setCurrentText(self.current_spec.method)
            self.url_edit.setText(self.current_spec.url)
            self.body_edit.setPlainText(self.current_spec.body)

            self.name_edit.blockSignals(False)
            self.method_combo.blockSignals(False)
            self.url_edit.blockSignals(False)
            self.body_edit.blockSignals(False)

            self.headers_table.blockSignals(True)
            self.headers_table.setRowCount(0)
            for h in self.current_spec.headers:
                self._insert_header_table_row(h.key, h.value, h.enabled)
            self.headers_table.blockSignals(False)

            for fid, cb in self.flag_checkboxes.items():
                cb.blockSignals(True)
                cb.setChecked(bool(self.current_spec.flags.get(fid, False)))
                cb.blockSignals(False)
            for fid, arg_in in self.flag_arg_inputs.items():
                arg_in.blockSignals(True)
                arg_in.setText(self.current_spec.flag_args.get(fid, CURL_FLAGS_MAP[fid].default_arg))
                arg_in.blockSignals(False)

            self._syncing_json = False
            self._sync_raw_body_to_json_table()
            self._refresh_outputs()
            self.on_execute_clicked()

        def _insert_header_table_row(self, key: str, val: str, enabled: bool) -> None:
            r = self.headers_table.rowCount()
            self.headers_table.insertRow(r)

            cb_item = QTableWidgetItem()
            cb_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            cb_item.setCheckState(Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked)
            self.headers_table.setItem(r, 0, cb_item)

            self.headers_table.setItem(r, 1, QTableWidgetItem(key))
            self.headers_table.setItem(r, 2, QTableWidgetItem(val))

            btn_del = QPushButton("×")
            btn_del.setMaximumWidth(32)
            btn_del.clicked.connect(lambda checked=False, row=r: self.remove_header_row(row))
            self.headers_table.setCellWidget(r, 3, btn_del)

        def add_header_row(self, key: str = "", val: str = "", enabled: bool = True) -> None:
            self.headers_table.blockSignals(True)
            self._insert_header_table_row(key, val, enabled)
            self.headers_table.blockSignals(False)
            self.on_headers_table_changed()

        def add_or_update_header(self, key: str, val: str) -> None:
            for r in range(self.headers_table.rowCount()):
                k_item = self.headers_table.item(r, 1)
                if k_item and k_item.text().strip().lower() == key.lower():
                    self.headers_table.item(r, 2).setText(val)
                    self.headers_table.item(r, 0).setCheckState(Qt.CheckState.Checked)
                    self.on_headers_table_changed()
                    return
            self.add_header_row(key, val, True)

        def remove_header_row(self, row: int) -> None:
            self.headers_table.removeRow(row)
            for r in range(self.headers_table.rowCount()):
                btn = self.headers_table.cellWidget(r, 3)
                if isinstance(btn, QPushButton):
                    try:
                        btn.clicked.disconnect()
                    except Exception:
                        pass
                    btn.clicked.connect(lambda checked=False, rr=r: self.remove_header_row(rr))
            self.on_headers_table_changed()

        def on_headers_table_changed(self, *_args: Any) -> None:
            headers: List[HeaderItem] = []
            for r in range(self.headers_table.rowCount()):
                cb_item = self.headers_table.item(r, 0)
                k_item = self.headers_table.item(r, 1)
                v_item = self.headers_table.item(r, 2)
                enabled = cb_item.checkState() == Qt.CheckState.Checked if cb_item else True
                key = k_item.text() if k_item else ""
                val = v_item.text() if v_item else ""
                headers.append(HeaderItem(key, val, enabled))
            self.current_spec.headers = headers
            self._refresh_outputs()

        def on_flags_ui_changed(self, *_args: Any) -> None:
            for fid, cb in self.flag_checkboxes.items():
                self.current_spec.flags[fid] = cb.isChecked()
            for fid, arg_in in self.flag_arg_inputs.items():
                self.current_spec.flag_args[fid] = arg_in.text().strip()
            self._refresh_outputs()

        def on_builder_changed(self, *_args: Any) -> None:
            self.current_spec.name = self.name_edit.text().strip() or "Custom Command"
            self.current_spec.method = self.method_combo.currentText()
            self.current_spec.url = self.url_edit.text().strip()
            self._refresh_outputs()

        def on_raw_body_text_changed(self) -> None:
            if self._syncing_json:
                return
            self.current_spec.body = self.body_edit.toPlainText()
            self._sync_raw_body_to_json_table()
            self._refresh_outputs()

        def _sync_raw_body_to_json_table(self) -> None:
            raw = self.body_edit.toPlainText().strip()
            self._syncing_json = True
            try:
                if not raw:
                    self.json_status_lbl.setText("Empty Body")
                    self.json_status_lbl.setStyleSheet("color: #5c6470;")
                    self.json_table.setRowCount(0)
                    return

                parsed = json.loads(raw)
                self.json_status_lbl.setText("Valid JSON ✓")
                self.json_status_lbl.setStyleSheet("color: #159a6a; font-weight: bold;")

                if isinstance(parsed, dict):
                    self.json_table.blockSignals(True)
                    self.json_table.setRowCount(0)
                    for row_idx, (k, v) in enumerate(parsed.items()):
                        self.json_table.insertRow(row_idx)
                        self.json_table.setItem(row_idx, 0, QTableWidgetItem(str(k)))

                        type_combo = QComboBox()
                        type_combo.addItems(["string", "number", "boolean", "json"])
                        if isinstance(v, bool):
                            type_combo.setCurrentText("boolean")
                            val_str = "true" if v else "false"
                        elif isinstance(v, (int, float)):
                            type_combo.setCurrentText("number")
                            val_str = str(v)
                        elif isinstance(v, str):
                            type_combo.setCurrentText("string")
                            val_str = v
                        else:
                            type_combo.setCurrentText("json")
                            val_str = json.dumps(v)

                        type_combo.currentTextChanged.connect(self.on_json_table_cell_changed)
                        self.json_table.setCellWidget(row_idx, 1, type_combo)
                        self.json_table.setItem(row_idx, 2, QTableWidgetItem(val_str))

                        btn_del = QPushButton("×")
                        btn_del.setMaximumWidth(32)
                        btn_del.clicked.connect(
                            lambda checked=False, key_to_del=k: self.on_delete_json_key(key_to_del)
                        )
                        self.json_table.setCellWidget(row_idx, 3, btn_del)
                    self.json_table.blockSignals(False)
            except Exception:
                self.json_status_lbl.setText("Invalid JSON Syntax ✗")
                self.json_status_lbl.setStyleSheet("color: #dc4c4c; font-weight: bold;")
            finally:
                self._syncing_json = False

        def on_json_table_cell_changed(self, *_args: Any) -> None:
            if self._syncing_json:
                return
            rebuilt: Dict[str, Any] = {}
            for r in range(self.json_table.rowCount()):
                k_item = self.json_table.item(r, 0)
                v_item = self.json_table.item(r, 2)
                type_widget = self.json_table.cellWidget(r, 1)
                if not k_item or not k_item.text().strip():
                    continue
                k = k_item.text().strip()
                raw_v = v_item.text() if v_item else ""
                t = type_widget.currentText() if isinstance(type_widget, QComboBox) else "string"

                if t == "number":
                    try:
                        rebuilt[k] = int(raw_v) if "." not in raw_v else float(raw_v)
                    except ValueError:
                        rebuilt[k] = 0
                elif t == "boolean":
                    rebuilt[k] = raw_v.strip().lower() in ("true", "1", "yes")
                elif t == "json":
                    try:
                        rebuilt[k] = json.loads(raw_v)
                    except Exception:
                        rebuilt[k] = raw_v
                else:
                    rebuilt[k] = raw_v

            self._syncing_json = True
            new_body = json.dumps(rebuilt)
            self.body_edit.setPlainText(new_body)
            self.current_spec.body = new_body
            self.json_status_lbl.setText("Valid JSON ✓")
            self.json_status_lbl.setStyleSheet("color: #159a6a; font-weight: bold;")
            self._syncing_json = False
            self._refresh_outputs()

        def on_add_json_key_row(self) -> None:
            try:
                raw = self.body_edit.toPlainText().strip()
                obj = json.loads(raw) if raw else {}
                if not isinstance(obj, dict):
                    obj = {}
            except Exception:
                obj = {}
            new_key = f"field_{len(obj) + 1}"
            obj[new_key] = "value"
            self.body_edit.setPlainText(json.dumps(obj))

        def on_delete_json_key(self, key: str) -> None:
            try:
                obj = json.loads(self.body_edit.toPlainText())
                if isinstance(obj, dict) and key in obj:
                    del obj[key]
                    self.body_edit.setPlainText(json.dumps(obj))
            except Exception:
                pass

        def on_prettify_json(self) -> None:
            try:
                obj = json.loads(self.body_edit.toPlainText())
                self.body_edit.setPlainText(json.dumps(obj, indent=2))
            except Exception:
                pass

        def on_minify_json(self) -> None:
            try:
                obj = json.loads(self.body_edit.toPlainText())
                self.body_edit.setPlainText(json.dumps(obj))
            except Exception:
                pass

        def _update_doctor_banner(self, raw_text: str) -> List[str]:
            warnings = diagnose_raw_curl(raw_text)
            if warnings:
                self.doctor_label.setText(
                    "Trainee Quote/Syntax Doctor:\n• " + "\n• ".join(warnings)
                )
                self.doctor_label.setStyleSheet(
                    "background-color: #fdf4e7; color: #8c530c; border: 1px solid #f0c987; "
                    "border-radius: 4px; padding: 6px 10px; font-size: 12px;"
                )
            else:
                self.doctor_label.setText(
                    "Syntax Check Passed ✓ — Quotes and URL scheme look clean."
                )
                self.doctor_label.setStyleSheet(
                    "background-color: #e8f6ee; color: #0f6e4b; border: 1px solid #a8dfc2; "
                    "border-radius: 4px; padding: 6px 10px; font-size: 12px;"
                )
            return warnings

        def on_parse_raw_clicked(self) -> None:
            raw = self.raw_curl_input.text()
            self._update_doctor_banner(raw)
            spec, _ = parse_raw_curl_command(raw, auto_fix_url=False)
            self.load_spec_into_ui(spec)
            self.status_bar.showMessage("Parsed raw cURL command into Visual Builder.", 4000)

        def on_autofix_raw_clicked(self) -> None:
            raw = self.raw_curl_input.text()
            spec, _ = parse_raw_curl_command(raw, auto_fix_url=True)
            if not any(h.key.lower() == "content-type" for h in spec.headers) and spec.body.strip().startswith("{"):
                spec.headers.insert(0, HeaderItem("Content-Type", "application/json", True))
            fixed_one_liner = format_command_for_shell(spec, "oneline")
            self.raw_curl_input.setText(fixed_one_liner)
            self._update_doctor_banner(fixed_one_liner)
            self.load_spec_into_ui(spec)
            self.status_bar.showMessage("Auto-fixed quotes, URL scheme, and headers!", 4000)

        def on_shell_format_changed(self) -> None:
            self.current_shell_fmt = self.shell_combo.currentData()
            self._refresh_outputs()

        def _refresh_outputs(self) -> None:
            cmd_str = format_command_for_shell(self.current_spec, self.current_shell_fmt)
            self.generated_cmd_edit.setPlainText(cmd_str)
            self.anatomy_browser.setHtml(generate_anatomy_html(self.current_spec))

        def on_copy_generated_command(self) -> None:
            cb = QGuiApplication.clipboard()
            cb.setText(self.generated_cmd_edit.toPlainText())
            self.status_bar.showMessage("Copied generated command to clipboard!", 3000)

        def on_execute_clicked(self) -> None:
            mode = self.exec_mode_combo.currentData()
            self.btn_run.setEnabled(False)
            self.btn_run.setText("Running...")
            self.worker = RequestWorker(
                CurlCommandSpec.from_dict(self.current_spec.to_dict()), mode
            )
            self.worker.finished_signal.connect(self.on_execution_finished)
            self.worker.start()

        def on_execution_finished(self, res: ExecutionResult) -> None:
            self.btn_run.setEnabled(True)
            self.btn_run.setText("Send Request / Run cURL")
            self.last_result = res

            self.resp_status_badge.setText(res.status_line)
            if res.ok:
                self.resp_status_badge.setStyleSheet(
                    "background-color: #e8f6ee; color: #159a6a; padding: 4px 10px; "
                    "border-radius: 4px; font-family: Consolas, monospace; font-weight: bold;"
                )
            else:
                self.resp_status_badge.setStyleSheet(
                    "background-color: #fdecec; color: #dc4c4c; padding: 4px 10px; "
                    "border-radius: 4px; font-family: Consolas, monospace; font-weight: bold;"
                )

            self.resp_time_lbl.setText(f"Time: {res.elapsed_ms} ms")
            self.resp_mode_lbl.setText(res.mode_used)

            self.resp_pretty_view.setPlainText(res.pretty_body)
            self.resp_headers_view.setPlainText(res.headers_text)
            self.resp_verbose_view.setPlainText(res.verbose_trace)

        def on_try_flag_from_encyclopedia(self, flag_id: str) -> None:
            if flag_id in self.flag_checkboxes:
                cb = self.flag_checkboxes[flag_id]
                cb.setChecked(not cb.isChecked())
                self.builder_subtabs.setCurrentIndex(2)
            self.main_tabs.setCurrentIndex(0)
            self.status_bar.showMessage(f"Toggled {CURL_FLAGS_MAP[flag_id].short} in Visual Builder.", 3000)

        def on_save_new_command(self) -> None:
            name, ok = QInputDialog.getText(
                self,
                "Save Custom Command",
                "Enter a name for this everyday command:",
                text=self.current_spec.name,
            )
            if ok and name.strip():
                self.current_spec.name = name.strip()
                self.name_edit.setText(self.current_spec.name)
                new_id = self.store.save_command(self.current_spec, row_id=None)
                self.current_row_id = new_id
                self._reload_saved_list(select_first=False)
                self.status_bar.showMessage(f"Saved '{self.current_spec.name}' to library!", 4000)

        def on_update_selected_command(self) -> None:
            if self.current_row_id is None:
                self.on_save_new_command()
                return
            self.store.save_command(self.current_spec, row_id=self.current_row_id)
            self._reload_saved_list(select_first=False)
            self.status_bar.showMessage(f"Updated '{self.current_spec.name}'!", 4000)

        def on_delete_selected_command(self) -> None:
            if self.current_row_id is None:
                return
            self.store.delete_command(self.current_row_id)
            self.current_row_id = None
            self._reload_saved_list(select_first=True)
            self.status_bar.showMessage("Deleted command from library.", 3000)

        def on_export_json(self) -> None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Export Saved Commands", "curl_saved_commands.json", "JSON Files (*.json)"
            )
            if path:
                records = [spec.to_dict() for _, spec in self.store.list_commands()]
                Path(path).write_text(json.dumps(records, indent=2), encoding="utf-8")
                self.status_bar.showMessage(f"Exported {len(records)} commands to {path}", 4000)

        def on_import_json(self) -> None:
            path, _ = QFileDialog.getOpenFileName(
                self, "Import Saved Commands", "", "JSON Files (*.json)"
            )
            if path:
                try:
                    data = json.loads(Path(path).read_text(encoding="utf-8"))
                    if isinstance(data, list):
                        for item in data:
                            self.store.save_command(CurlCommandSpec.from_dict(item))
                        self._reload_saved_list(select_first=True)
                        self.status_bar.showMessage(f"Imported {len(data)} commands!", 4000)
                except Exception as exc:
                    QMessageBox.warning(self, "Import Error", f"Could not import JSON:\n{exc}")
