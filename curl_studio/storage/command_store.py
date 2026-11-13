"""SQLite persistence for everyday saved cURL commands and LLM provider configuration."""

from __future__ import annotations
import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from ..core.models import CurlCommandSpec, HeaderItem


@dataclass
class LLMSettings:
    provider: str = "ollama"  # 'ollama' | 'openai_compat' | 'anthropic' | 'builtin_coach'
    base_url: str = "http://localhost:11434/v1/chat/completions"
    model_name: str = "llama3.2"
    api_key: str = ""
    temperature: float = 0.2
    enable_mcp_tools: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "base_url": self.base_url,
            "model_name": self.model_name,
            "api_key": self.api_key,
            "temperature": self.temperature,
            "enable_mcp_tools": self.enable_mcp_tools,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "LLMSettings":
        return LLMSettings(
            provider=str(d.get("provider", "ollama")),
            base_url=str(d.get("base_url", "http://localhost:11434/v1/chat/completions")),
            model_name=str(d.get("model_name", "llama3.2")),
            api_key=str(d.get("api_key", "")),
            temperature=float(d.get("temperature", 0.2)),
            enable_mcp_tools=bool(d.get("enable_mcp_tools", True)),
        )


class CommandLibraryStore:
    """Persists saved & custom curl commands and LLM settings in SQLite (~/.curl_studio/commands.db)."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        if db_path is None:
            base_dir = Path.home() / ".curl_studio"
            base_dir.mkdir(parents=True, exist_ok=True)
            db_path = base_dir / "commands.db"
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS saved_commands (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    spec_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL
                )
                """
            )
            cur = conn.execute("SELECT COUNT(*) FROM saved_commands")
            if cur.fetchone()[0] == 0:
                self.seed_defaults(conn)

    def seed_defaults(self, conn: Optional[sqlite3.Connection] = None) -> None:
        defaults = [
            CurlCommandSpec(
                name="1. Your Product Order POST (101)",
                method="POST",
                url="http://sdfble",
                headers=[HeaderItem("Content-Type", "application/json", True)],
                body='{"product_id": "101", "quantity": 1, "price": 0.01}',
                flags={"flag_i": True},
            ),
            CurlCommandSpec(
                name="2. Fixed Localhost Order POST (101)",
                method="POST",
                url="http://localhost:8000/api/orders",
                headers=[
                    HeaderItem("Content-Type", "application/json", True),
                    HeaderItem("Accept", "application/json", True),
                ],
                body='{"product_id": "101", "quantity": 1, "price": 0.01}',
                flags={"flag_i": True, "flag_v": True},
            ),
            CurlCommandSpec(
                name="3. Authenticated Station Status GET",
                method="GET",
                url="https://192.168.10.45:8443/api/v1/stations/FVT-02",
                headers=[
                    HeaderItem("Authorization", "Bearer YOUR_API_TOKEN", True),
                    HeaderItem("Accept", "application/json", True),
                ],
                body="",
                flags={"flag_i": True, "flag_k": True, "flag_L": True, "flag_m": True},
            ),
            CurlCommandSpec(
                name="4. Basic Auth Config Check (-u + -v)",
                method="GET",
                url="http://10.0.0.25:5000/api/config",
                headers=[HeaderItem("X-Station-ID", "MAGNETO-TLA-04", True)],
                body="",
                flags={"flag_v": True, "flag_u": True, "flag_m": True, "flag_w": True},
            ),
        ]
        own_conn = False
        if conn is None:
            conn = sqlite3.connect(self.db_path)
            own_conn = True
        try:
            conn.execute("DELETE FROM saved_commands")
            for idx, spec in enumerate(defaults):
                conn.execute(
                    "INSERT INTO saved_commands (name, spec_json, created_at) VALUES (?, ?, ?)",
                    (spec.name, json.dumps(spec.to_dict()), time.time() + idx),
                )
            conn.commit()
        finally:
            if own_conn:
                conn.close()

    def list_commands(self) -> List[Tuple[int, CurlCommandSpec]]:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("SELECT id, spec_json FROM saved_commands ORDER BY id ASC")
            results: List[Tuple[int, CurlCommandSpec]] = []
            for row_id, s_json in cur.fetchall():
                try:
                    results.append((row_id, CurlCommandSpec.from_dict(json.loads(s_json))))
                except Exception:
                    pass
            return results

    def get_command_by_id(self, row_id: int) -> Optional[CurlCommandSpec]:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("SELECT spec_json FROM saved_commands WHERE id = ?", (row_id,))
            row = cur.fetchone()
            if row:
                return CurlCommandSpec.from_dict(json.loads(row[0]))
            return None

    def save_command(self, spec: CurlCommandSpec, row_id: Optional[int] = None) -> int:
        with sqlite3.connect(self.db_path) as conn:
            if row_id is not None:
                conn.execute(
                    "UPDATE saved_commands SET name = ?, spec_json = ? WHERE id = ?",
                    (spec.name, json.dumps(spec.to_dict()), row_id),
                )
                conn.commit()
                return row_id
            else:
                cur = conn.execute(
                    "INSERT INTO saved_commands (name, spec_json, created_at) VALUES (?, ?, ?)",
                    (spec.name, json.dumps(spec.to_dict()), time.time()),
                )
                conn.commit()
                return int(cur.lastrowid)

    def delete_command(self, row_id: int) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM saved_commands WHERE id = ?", (row_id,))
            conn.commit()

    def load_llm_settings(self) -> LLMSettings:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("SELECT value_json FROM app_settings WHERE key = 'llm_settings'")
            row = cur.fetchone()
            if row:
                try:
                    return LLMSettings.from_dict(json.loads(row[0]))
                except Exception:
                    pass
        return LLMSettings()

    def save_llm_settings(self, settings: LLMSettings) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO app_settings (key, value_json) VALUES ('llm_settings', ?)",
                (json.dumps(settings.to_dict()),),
            )
            conn.commit()
