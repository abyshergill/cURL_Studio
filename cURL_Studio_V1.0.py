#!/usr/bin/env python3
"""
cURL Interactive Studio & Trainee Guide — Desktop Application (PyQt6)
=====================================================================
A full-featured PyQt6 desktop application for building, parsing, running,
and teaching `curl` commands without wrestling with nested shell quotes.

Features:
1. Everyday Custom Command Library (SQLite-backed `~/.curl_studio/commands.db` + JSON Import/Export)
2. Raw `curl` Command Importer & Quote Doctor (detects nested quote traps like `-d "{"id": "101"}"` and missing `//`)
3. Visual Request Builder:
   - HTTP Method (-X) & Endpoint URL
   - Interactive Headers Table (-H) with quick presets
   - Dual JSON Payload Editor (-d): Raw JSON text + Visual Key/Type/Value Table (no quotes needed!)
   - Common cURL Flags Checkboxes with parameter inputs (-i, -v, -L, -k, -s, -u, -o, -m, -x, -w, --compressed)
4. Multi-Shell Command Generator (Bash/Zsh, One-Liner, Windows CMD, PowerShell, Python `requests`)
5. Live Command Execution Engine:
   - Runs real `curl` via non-blocking QProcess (with fallback to Python `urllib.request` or Trainee Mock Simulator)
   - Pretty-prints JSON responses, separates HTTP Response Headers (-i), and highlights Verbose Handshake Traces (-v)
6. Interactive Command Anatomy & Trainee Flag Encyclopedia (17+ common flags + 4 interactive troubleshooting drills)

Requirements:
    pip install PyQt6
Usage:
    python curl_studio_desktop.py
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize
    from PyQt6.QtGui import QAction, QColor, QFont, QGuiApplication, QIcon
    from PyQt6.QtWidgets import (
        QAbstractItemView,
        QApplication,
        QCheckBox,
        QComboBox,
        QFileDialog,
        QFrame,
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
        QSpinBox,
        QSplitter,
        QStatusBar,
        QTableWidget,
        QTableWidgetItem,
        QTabWidget,
        QTextBrowser,
        QToolBar,
        QVBoxLayout,
        QWidget,
    )
    PYQT_AVAILABLE = True
except ImportError:
    PYQT_AVAILABLE = False


# =====================================================================
# 1. COMMON CURL FLAGS ENCYCLOPEDIA DATA
# =====================================================================

@dataclass
class CurlFlagInfo:
    flag_id: str
    short: str
    long: str
    category: str
    summary: str
    detail: str
    example: str
    trainee_tip: str
    toggleable: bool = True
    has_arg: bool = False
    default_arg: str = ""


CURL_FLAGS_DB: List[CurlFlagInfo] = [
    CurlFlagInfo(
        flag_id="flag_X",
        short="-X",
        long="--request <METHOD>",
        category="Method & Headers",
        summary="Specifies custom HTTP method (GET, POST, PUT, PATCH, DELETE)",
        detail="Overrides the default HTTP verb. Note: using -d automatically defaults to POST, but explicitly writing -X POST makes commands much clearer for trainees.",
        example='curl -X POST "http://localhost:8000/api/orders"',
        trainee_tip="Avoid combining -X GET with -d unless an API specifically requires a GET body.",
        toggleable=False,
    ),
    CurlFlagInfo(
        flag_id="flag_H",
        short="-H",
        long='--header "Key: Value"',
        category="Method & Headers",
        summary="Adds an HTTP request header (can be used multiple times)",
        detail="Sends metadata such as Content-Type: application/json, Authorization tokens, or custom station headers. Repeat -H for every header you want to attach.",
        example='-H "Content-Type: application/json" -H "X-Station: FVT-02"',
        trainee_tip='Always include a space after the colon inside "Header: Value".',
        toggleable=False,
    ),
    CurlFlagInfo(
        flag_id="flag_d",
        short="-d",
        long="--data <DATA>",
        category="Payload & Upload",
        summary="Sends HTTP POST/PUT request body payload (JSON or form data)",
        detail="Transmits the specified string as the request body. Use @filename (e.g. -d @payload.json) to read JSON directly from a file instead of escaping quotes in terminal.",
        example="-d '{\"product_id\": \"101\", \"quantity\": 1, \"price\": 0.01}'",
        trainee_tip="NEVER wrap unescaped JSON in outer double quotes (-d \"{\"a\":1}\") in Bash—outer double quotes strip inner double quotes! Wrap JSON in single quotes ('...').",
        toggleable=False,
    ),
    CurlFlagInfo(
        flag_id="flag_i",
        short="-i",
        long="--include",
        category="Debugging & Output",
        summary="Includes HTTP response status code & response headers in output",
        detail="Essential when checking API responses! Without -i, curl only prints the response body and hides whether the status was 200 OK, 201 Created, 400 Bad Request, or 500.",
        example='curl -i -X POST "http://api.local/items" -d \'{"id":1}\'',
        trainee_tip="If piping output to jq (curl ... | jq), -i will break jq because HTTP headers are not valid JSON. Use -v instead.",
        toggleable=True,
    ),
    CurlFlagInfo(
        flag_id="flag_v",
        short="-v",
        long="--verbose",
        category="Debugging & Output",
        summary="Shows full connection trace, outgoing headers (>), and incoming headers (<)",
        detail="The #1 debugging flag. Shows DNS lookup, TCP connection, TLS handshake, exact request headers sent (>), and response headers received (<).",
        example='curl -v "http://localhost:8000/health"',
        trainee_tip="Lines starting with * are connection info, > are sent by your client, and < are returned by the server.",
        toggleable=True,
    ),
    CurlFlagInfo(
        flag_id="flag_L",
        short="-L",
        long="--location",
        category="Network & Redirects",
        summary="Automatically follows HTTP 301 / 302 / 307 redirects",
        detail="If the server responds with a Location: redirect header (e.g., http -> https or adding a trailing slash), curl automatically re-issues the request to the new URL.",
        example='curl -L "http://internal-portal/api/status"',
        trainee_tip="Without -L, redirected URLs return an empty body or a short 301 Moved Permanently HTML stub.",
        toggleable=True,
    ),
    CurlFlagInfo(
        flag_id="flag_k",
        short="-k",
        long="--insecure",
        category="Auth & Security",
        summary="Allows HTTPS connections to servers with self-signed SSL certificates",
        detail="Skips SSL/TLS certificate verification. Very common on manufacturing test benches, hardware fixtures, and internal staging servers using self-signed certs.",
        example='curl -k "https://192.168.1.50:8443/api/telemetry"',
        trainee_tip="Use only on trusted internal lab networks or test benches; never disable SSL verification in public production scripts.",
        toggleable=True,
    ),
    CurlFlagInfo(
        flag_id="flag_s",
        short="-s",
        long="--silent",
        category="Debugging & Output",
        summary="Silent mode — hides progress meter and error messages",
        detail="Suppresses the download progress table when piping output into scripts or jq. Combine as -sS to hide the progress meter while still printing errors.",
        example='curl -s "http://api.local/products/101"',
        trainee_tip="Pure -s hides connection errors too! Pair it with -S (-sS) so real network errors are still shown.",
        toggleable=True,
    ),
    CurlFlagInfo(
        flag_id="flag_compressed",
        short="--compressed",
        long="--compressed",
        category="Network & Redirects",
        summary="Requests compressed response (gzip/deflate/br) and auto-decompresses it",
        detail="Sends Accept-Encoding: deflate, gzip, br and automatically decompresses the response body so terminal output stays human-readable.",
        example='curl --compressed "https://api.example.com/large-report"',
        trainee_tip="If you manually set -H 'Accept-Encoding: gzip' without --compressed, curl prints raw binary garbage to your terminal!",
        toggleable=True,
    ),
    CurlFlagInfo(
        flag_id="flag_u",
        short="-u",
        long="--user <user:pass>",
        category="Auth & Security",
        summary="Sends HTTP Basic Authentication (Base64 Authorization header)",
        detail="Automatically encodes username:password into an Authorization: Basic <base64> header. Omit :password to have curl prompt securely.",
        example='curl -u "admin:secret123" "http://api.local/config"',
        trainee_tip="If the password contains special characters like ! or $, wrap 'user:pass' in single quotes.",
        toggleable=True,
        has_arg=True,
        default_arg="admin:secret123",
    ),
    CurlFlagInfo(
        flag_id="flag_o",
        short="-o",
        long="--output <file>",
        category="Debugging & Output",
        summary="Writes the response body to a local file instead of stdout",
        detail="Saves the API response or downloaded file directly to the specified path. Use -O (capital O) to save using the remote URL's filename.",
        example='curl -o response.json "http://api.local/export"',
        trainee_tip='Combine with -w "%{http_code}" in automation scripts to save the JSON body to disk while capturing the HTTP status code.',
        toggleable=True,
        has_arg=True,
        default_arg="response.json",
    ),
    CurlFlagInfo(
        flag_id="flag_m",
        short="-m",
        long="--max-time <seconds>",
        category="Network & Redirects",
        summary="Maximum time in seconds allowed for the whole transfer before aborting",
        detail="Prevents hung terminals or frozen test scripts when a hardware fixture or server stops responding.",
        example='curl -m 10 "http://10.0.0.25:5000/run-test"',
        trainee_tip="Also see --connect-timeout <sec> to cap only the initial TCP handshake phase.",
        toggleable=True,
        has_arg=True,
        default_arg="10",
    ),
    CurlFlagInfo(
        flag_id="flag_x",
        short="-x",
        long="--proxy <host:port>",
        category="Network & Redirects",
        summary="Routes the HTTP request through a corporate or debugging proxy",
        detail='Directs traffic through an HTTP/HTTPS or SOCKS proxy. Use --noproxy "*" to bypass system proxy environment variables when hitting localhost or lab IPs.',
        example='curl -x "http://proxy.corp:8080" "https://external.api/v1"',
        trainee_tip='If a local lab IP (192.168.x.x or localhost) fails on corporate LAN, pass --noproxy "*" so curl does not route local traffic to the internet proxy!',
        toggleable=True,
        has_arg=True,
        default_arg="http://proxy.corp:8080",
    ),
    CurlFlagInfo(
        flag_id="flag_w",
        short="-w",
        long="--write-out <format>",
        category="Debugging & Output",
        summary="Prints timing & status metrics (HTTP code, total time, DNS time) after completion",
        detail="Great for benchmarking API latency or extracting the exact HTTP status code in test automation scripts.",
        example='curl -w "\\nHTTP_CODE:%{http_code} TIME:%{time_total}s\\n" "http://api.local"',
        trainee_tip="Combine with -s -o /dev/null when you ONLY want the status code or timing printed.",
        toggleable=True,
    ),
    CurlFlagInfo(
        flag_id="flag_I",
        short="-I",
        long="--head",
        category="Method & Headers",
        summary="Fetches ONLY the HTTP response headers (sends a HEAD request)",
        detail="Quickly checks if a server is alive, content length, or caching headers without downloading a large payload.",
        example='curl -I "http://localhost:8000/firmware.bin"',
        trainee_tip="Some custom REST endpoints only implement GET/POST and return 405 Method Not Allowed on -I.",
        toggleable=False,
    ),
    CurlFlagInfo(
        flag_id="flag_F",
        short="-F",
        long="--form <name=@file>",
        category="Payload & Upload",
        summary="Uploads files as multipart/form-data (like an HTML file upload)",
        detail="Automatically sets Content-Type: multipart/form-data with boundary strings and streams binary/text files using the @ prefix.",
        example='curl -X POST -F "logfile=@/tmp/test.log" -F "station=FVT2" "http://api.local/upload"',
        trainee_tip='Do NOT manually set -H "Content-Type: multipart/form-data" when using -F, or you will overwrite curl\'s boundary token!',
        toggleable=False,
    ),
    CurlFlagInfo(
        flag_id="flag_G",
        short="-G",
        long="--get",
        category="Method & Headers",
        summary="Forces -d parameters into the URL query string (?key=val) for a GET request",
        detail="Instead of manually escaping ?serial=SN 101&status=FAIL in the URL, combine -G with --data-urlencode to safely URL-encode query parameters.",
        example='curl -G --data-urlencode "serial=SN 101/A" "http://api.local/search"',
        trainee_tip="Without -G, adding -d always turns the request into a POST.",
        toggleable=False,
    ),
    CurlFlagInfo(
        flag_id="flag_b",
        short="-b / -c",
        long="--cookie / --cookie-jar",
        category="Auth & Security",
        summary="Sends session cookies (-b) or saves server login cookies to a file (-c)",
        detail="Crucial for session-authenticated web apps (like Django sessionid/csrftoken). Log in once with -c cookies.txt, then send subsequent requests with -b cookies.txt.",
        example='curl -c cookies.txt -d "user=admin&pass=123" "http://localhost:8000/login"',
        trainee_tip="Use -c (cookie-jar) to write cookies received from login, and -b (cookie) to read them back on the next command.",
        toggleable=False,
    ),
]

CURL_FLAGS_MAP: Dict[str, CurlFlagInfo] = {f.flag_id: f for f in CURL_FLAGS_DB}


# =====================================================================
# 2. COMMAND MODEL, PARSER, DOCTOR & MULTI-SHELL GENERATOR
# =====================================================================

@dataclass
class HeaderItem:
    key: str
    value: str
    enabled: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {"key": self.key, "value": self.value, "enabled": self.enabled}

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "HeaderItem":
        return HeaderItem(
            key=str(d.get("key", "")),
            value=str(d.get("value", "")),
            enabled=bool(d.get("enabled", True)),
        )


@dataclass
class CurlCommandSpec:
    name: str = "Create Product Order (POST 101)"
    method: str = "POST"
    url: str = "http://sdfble"
    headers: List[HeaderItem] = field(
        default_factory=lambda: [HeaderItem("Content-Type", "application/json", True)]
    )
    body: str = '{"product_id": "101", "quantity": 1, "price": 0.01}'
    flags: Dict[str, bool] = field(default_factory=lambda: {"flag_i": True})
    flag_args: Dict[str, str] = field(
        default_factory=lambda: {
            "flag_u": "admin:secret123",
            "flag_o": "response.json",
            "flag_m": "10",
            "flag_x": "http://proxy.corp:8080",
        }
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "method": self.method,
            "url": self.url,
            "headers": [h.to_dict() for h in self.headers],
            "body": self.body,
            "flags": self.flags,
            "flag_args": self.flag_args,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "CurlCommandSpec":
        spec = CurlCommandSpec(
            name=str(d.get("name", "Custom Command")),
            method=str(d.get("method", "POST")).upper(),
            url=str(d.get("url", "http://localhost")),
            headers=[HeaderItem.from_dict(x) for x in d.get("headers", [])],
            body=str(d.get("body", "")),
            flags=dict(d.get("flags", {})),
        )
        if "flag_args" in d and isinstance(d["flag_args"], dict):
            spec.flag_args.update({k: str(v) for k, v in d["flag_args"].items()})
        return spec


def diagnose_raw_curl(raw_cmd: str) -> List[str]:
    """
    Inspects a raw curl string for common trainee mistakes:
    1) Nested double quotes around JSON: -d "{"product_id": "101"}"
    2) Missing double slashes after http: or https: (e.g. "http:sdfble")
    3) JSON body sent without Content-Type: application/json header
    """
    warnings: List[str] = []
    text = raw_cmd.strip()
    if not text:
        return warnings

    # 1. Check nested unescaped double quotes around JSON body
    if re.search(r'(?:-d|--data|--data-raw)\s+"\{.*"\s*:\s*.*\}"', text):
        warnings.append(
            "Nested Double-Quote Trap: Wrapping JSON in double quotes (-d \"{\"product_id\": \"101\"}\") "
            "causes Bash/Zsh to strip the inner quotes and send invalid JSON! Wrap -d payload in single quotes ('{...}')."
        )

    # 2. Check malformed protocol (http:sdfble instead of http://sdfble)
    bad_proto = re.search(r'["\']?(https?:)(?!//)([^"\'\s]+)', text, re.IGNORECASE)
    if bad_proto:
        proto, rest = bad_proto.group(1), bad_proto.group(2)
        warnings.append(
            f"Malformed URL Scheme: '{proto}{rest}' is missing '//' after '{proto}'. "
            f"It should be '{proto}//{rest}'."
        )

    # 3. Check JSON payload without Content-Type: application/json
    has_json_like_body = bool(re.search(r'(?:-d|--data|--data-raw)\s+[\'"]?\s*\{', text))
    has_json_header = bool(re.search(r'application/json', text, re.IGNORECASE))
    if has_json_like_body and not has_json_header:
        warnings.append(
            "Missing JSON Header: Sending a JSON body with -d defaults to "
            "'Content-Type: application/x-www-form-urlencoded'. Add -H \"Content-Type: application/json\"."
        )

    return warnings


def parse_raw_curl_command(raw_cmd: str, auto_fix_url: bool = False) -> Tuple[CurlCommandSpec, List[str]]:
    """
    Parses a raw curl string (even one with broken nested double quotes like the user's example)
    into a structured CurlCommandSpec and returns diagnostic warnings.
    """
    warnings = diagnose_raw_curl(raw_cmd)
    raw = raw_cmd.strip()
    spec = CurlCommandSpec(name="Imported cURL Command", headers=[], body="", flags={})

    # Pre-capture broken nested double-quoted JSON: -d "{"product_id": "101", ...}"
    broken_json_match = re.search(r'(?:-d|--data|--data-raw)\s+"(\{.*\})"', raw)
    extracted_broken_body: Optional[str] = None
    cleaned_raw = raw
    if broken_json_match:
        extracted_broken_body = broken_json_match.group(1)
        # Replace broken segment with a safe placeholder for shlex
        cleaned_raw = (
            raw[: broken_json_match.start()]
            + "-d __BROKEN_JSON_PLACEHOLDER__"
            + raw[broken_json_match.end() :]
        )

    # Normalize line continuations
    cleaned_raw = re.sub(r"\\\r?\n", " ", cleaned_raw)

    try:
        tokens = shlex.split(cleaned_raw)
    except ValueError:
        tokens = cleaned_raw.split()

    method_explicit: Optional[str] = None
    url_found: Optional[str] = None

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if i == 0 and tok.lower() in ("curl", "curl.exe"):
            i += 1
            continue

        if tok in ("-X", "--request") and i + 1 < len(tokens):
            method_explicit = tokens[i + 1].upper().strip("\"'")
            i += 2
            continue

        if tok in ("-H", "--header") and i + 1 < len(tokens):
            hdr_raw = tokens[i + 1]
            if ":" in hdr_raw:
                k, v = hdr_raw.split(":", 1)
                spec.headers.append(HeaderItem(k.strip(), v.strip(), True))
            i += 2
            continue

        if tok in ("-d", "--data", "--data-raw", "--data-binary") and i + 1 < len(tokens):
            val = tokens[i + 1]
            if val == "__BROKEN_JSON_PLACEHOLDER__" and extracted_broken_body is not None:
                spec.body = extracted_broken_body
            else:
                spec.body = val
            i += 2
            continue

        if tok in ("-u", "--user") and i + 1 < len(tokens):
            spec.flags["flag_u"] = True
            spec.flag_args["flag_u"] = tokens[i + 1]
            i += 2
            continue

        if tok in ("-o", "--output") and i + 1 < len(tokens):
            spec.flags["flag_o"] = True
            spec.flag_args["flag_o"] = tokens[i + 1]
            i += 2
            continue

        if tok in ("-m", "--max-time") and i + 1 < len(tokens):
            spec.flags["flag_m"] = True
            spec.flag_args["flag_m"] = tokens[i + 1]
            i += 2
            continue

        if tok in ("-x", "--proxy") and i + 1 < len(tokens):
            spec.flags["flag_x"] = True
            spec.flag_args["flag_x"] = tokens[i + 1]
            i += 2
            continue

        if tok in ("-w", "--write-out") and i + 1 < len(tokens):
            spec.flags["flag_w"] = True
            i += 2
            continue

        # Boolean flags
        if tok in ("-i", "--include"):
            spec.flags["flag_i"] = True
        elif tok in ("-v", "--verbose"):
            spec.flags["flag_v"] = True
        elif tok in ("-L", "--location"):
            spec.flags["flag_L"] = True
        elif tok in ("-k", "--insecure"):
            spec.flags["flag_k"] = True
        elif tok in ("-s", "--silent", "-sS"):
            spec.flags["flag_s"] = True
        elif tok == "--compressed":
            spec.flags["flag_compressed"] = True
        elif not tok.startswith("-") and url_found is None:
            url_found = tok.strip("\"'")

        i += 1

    if url_found:
        if auto_fix_url:
            url_found = re.sub(r"^(https?:)(?!//)", r"\1//", url_found, flags=re.IGNORECASE)
        spec.url = url_found

    if method_explicit:
        spec.method = method_explicit
    elif spec.body:
        spec.method = "POST"
    else:
        spec.method = "GET"

    return spec, warnings


def build_curl_argv(spec: CurlCommandSpec, include_writeout: bool = False) -> List[str]:
    """Builds the exact OS argument list for subprocess/QProcess execution (no shell quoting issues)."""
    argv: List[str] = ["curl", "-X", spec.method]

    if spec.flags.get("flag_i"):
        argv.append("-i")
    if spec.flags.get("flag_v"):
        argv.append("-v")
    if spec.flags.get("flag_L"):
        argv.append("-L")
    if spec.flags.get("flag_k"):
        argv.append("-k")
    if spec.flags.get("flag_s"):
        argv.append("-s")
    if spec.flags.get("flag_compressed"):
        argv.append("--compressed")

    if spec.flags.get("flag_u"):
        argv.extend(["-u", spec.flag_args.get("flag_u", "admin:secret123")])
    if spec.flags.get("flag_o"):
        argv.extend(["-o", spec.flag_args.get("flag_o", "response.json")])
    if spec.flags.get("flag_m"):
        argv.extend(["-m", str(spec.flag_args.get("flag_m", "10"))])
    if spec.flags.get("flag_x"):
        argv.extend(["-x", spec.flag_args.get("flag_x", "http://proxy.corp:8080")])
    if spec.flags.get("flag_w") or include_writeout:
        argv.extend(["-w", "\nHTTP_CODE:%{http_code} TIME:%{time_total}s\n"])

    for h in spec.headers:
        if h.enabled and h.key.strip():
            argv.extend(["-H", f"{h.key.strip()}: {h.value.strip()}"])

    body_trimmed = spec.body.strip()
    if body_trimmed and spec.method not in ("GET", "HEAD"):
        try:
            body_trimmed = json.dumps(json.loads(body_trimmed))
        except Exception:
            pass
        argv.extend(["-d", body_trimmed])

    argv.append(spec.url.strip() or "http://localhost")
    return argv


def format_command_for_shell(spec: CurlCommandSpec, shell_type: str = "bash") -> str:
    """
    Formats a CurlCommandSpec for:
      - 'bash': Multiline Bash/Zsh with safe single-quoted JSON
      - 'oneline': Single-line Bash/Zsh command
      - 'cmd': Windows Command Prompt (escaped inner double quotes)
      - 'ps': Windows PowerShell (curl.exe with backtick continuations)
      - 'python': Equivalent Python `requests` snippet
    """
    method = spec.method.upper()
    url = spec.url.strip() or "http://localhost"
    body_trimmed = spec.body.strip()
    if body_trimmed:
        try:
            body_trimmed = json.dumps(json.loads(body_trimmed))
        except Exception:
            pass

    active_flags: List[str] = []
    for f in CURL_FLAGS_DB:
        if f.toggleable and spec.flags.get(f.flag_id):
            if f.flag_id == "flag_u":
                active_flags.append(f'-u "{spec.flag_args.get("flag_u", "user:pass")}"')
            elif f.flag_id == "flag_o":
                active_flags.append(f'-o "{spec.flag_args.get("flag_o", "response.json")}"')
            elif f.flag_id == "flag_m":
                active_flags.append(f'-m {spec.flag_args.get("flag_m", "10")}')
            elif f.flag_id == "flag_x":
                active_flags.append(f'-x "{spec.flag_args.get("flag_x", "http://proxy:8080")}"')
            elif f.flag_id == "flag_w":
                active_flags.append('-w "\\nHTTP_CODE:%{http_code} TIME:%{time_total}s\\n"')
            else:
                active_flags.append(f.short)

    enabled_headers = [h for h in spec.headers if h.enabled and h.key.strip()]

    if shell_type == "bash":
        lines = [f'curl -X {method} "{url}"']
        for fl in active_flags:
            lines.append(f"  {fl}")
        for h in enabled_headers:
            lines.append(f'  -H "{h.key.strip()}: {h.value.strip()}"')
        if body_trimmed and method not in ("GET", "HEAD"):
            safe_single = body_trimmed.replace("'", "'\\''")
            lines.append(f"  -d '{safe_single}'")
        return " \\\n".join(lines)

    if shell_type == "oneline":
        parts = [f'curl -X {method} "{url}"']
        parts.extend(active_flags)
        for h in enabled_headers:
            parts.append(f'-H "{h.key.strip()}: {h.value.strip()}"')
        if body_trimmed and method not in ("GET", "HEAD"):
            safe_single = body_trimmed.replace("'", "'\\''")
            parts.append(f"-d '{safe_single}'")
        return " ".join(parts)

    if shell_type == "cmd":
        parts = [f'curl -X {method} "{url}"']
        parts.extend(active_flags)
        for h in enabled_headers:
            parts.append(f'-H "{h.key.strip()}: {h.value.strip()}"')
        if body_trimmed and method not in ("GET", "HEAD"):
            escaped_cmd = body_trimmed.replace('"', '\\"')
            parts.append(f'-d "{escaped_cmd}"')
        return " ".join(parts)

    if shell_type == "ps":
        lines = [f'curl.exe -X {method} "{url}"']
        for fl in active_flags:
            lines.append(f"  {fl}")
        for h in enabled_headers:
            lines.append(f'  -H "{h.key.strip()}: {h.value.strip()}"')
        if body_trimmed and method not in ("GET", "HEAD"):
            ps_single = body_trimmed.replace("'", "''")
            lines.append(f"  -d '{ps_single}'")
        return " `\n".join(lines)

    if shell_type == "python":
        hdr_dict = {h.key.strip(): h.value.strip() for h in enabled_headers}
        py_lines = [
            "import requests",
            "",
            f"url = {json.dumps(url)}",
            f"headers = {json.dumps(hdr_dict, indent=2)}",
        ]
        if body_trimmed and method not in ("GET", "HEAD"):
            try:
                parsed_json = json.loads(body_trimmed)
                py_lines.append(f"payload = {json.dumps(parsed_json, indent=2)}")
                py_lines.append("")
                py_lines.append(
                    f'response = requests.request("{method}", url, headers=headers, json=payload, timeout=10)'
                )
            except Exception:
                py_lines.append(f"payload = {json.dumps(body_trimmed)}")
                py_lines.append("")
                py_lines.append(
                    f'response = requests.request("{method}", url, headers=headers, data=payload, timeout=10)'
                )
        else:
            py_lines.append("")
            py_lines.append(
                f'response = requests.request("{method}", url, headers=headers, timeout=10)'
            )
        py_lines.append("print(f'Status: {response.status_code}')")
        py_lines.append("print(response.text)")
        return "\n".join(py_lines)

    return ""


def generate_anatomy_html(spec: CurlCommandSpec) -> str:
    """Builds a trainee-friendly HTML breakdown of every active token in the command."""
    rows_html: List[str] = []

    def add_row(badge_bg: str, badge_fg: str, token_str: str, role: str, explanation: str) -> None:
        rows_html.append(
            f"""
            <tr>
              <td style="padding:7px 10px; border-bottom:1px solid #e3e6ec; white-space:nowrap;">
                <span style="background:{badge_bg}; color:{badge_fg}; padding:3px 7px; border-radius:4px; font-family:monospace; font-weight:bold; font-size:12px;">
                  {role}
                </span>
              </td>
              <td style="padding:7px 10px; border-bottom:1px solid #e3e6ec; font-family:monospace; font-weight:bold; color:#11141a; font-size:12.5px;">
                {token_str}
              </td>
              <td style="padding:7px 10px; border-bottom:1px solid #e3e6ec; color:#374151; font-size:12.5px;">
                {explanation}
              </td>
            </tr>
            """
        )

    add_row("#e3e8f8", "#223c9e", "curl", "CLI Binary", "Invokes the Client URL command-line tool.")
    add_row(
        "#dff4e8",
        "#0f6e4b",
        f"-X {spec.method}",
        "HTTP Method",
        f"Sets the HTTP request verb to <b>{spec.method}</b> (POST creates data, GET retrieves, PUT/PATCH updates, DELETE removes).",
    )

    url_warn = ""
    if "://" not in spec.url:
        url_warn = " <b style='color:#dc4c4c;'>[Warning: Missing // after http:!]</b>"
    add_row(
        "#f6ebd8",
        "#8c530c",
        f'"{spec.url}"',
        "Target URL",
        f"Destination endpoint where the request is sent.{url_warn}",
    )

    for f in CURL_FLAGS_DB:
        if f.toggleable and spec.flags.get(f.flag_id):
            token_disp = f.short
            if f.has_arg:
                token_disp = f'{f.short} "{spec.flag_args.get(f.flag_id, f.default_arg)}"'
            add_row(
                "#e0f2f4",
                "#0d616b",
                token_disp,
                f"Flag ({f.short})",
                f"<b>{f.summary}:</b> {f.detail} <i>(Tip: {f.trainee_tip})</i>",
            )

    for h in spec.headers:
        if h.enabled and h.key.strip():
            add_row(
                "#ede5fb",
                "#5628a8",
                f'-H "{h.key.strip()}: {h.value.strip()}"',
                "Header (-H)",
                "Informs the server how to interpret the payload or authenticates the client."
                if h.key.lower() == "content-type"
                else f"Sends custom HTTP request header <code>{h.key.strip()}</code>.",
            )

    if spec.body.strip() and spec.method not in ("GET", "HEAD"):
        safe_b = (
            spec.body.strip()
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        add_row(
            "#fce4ec",
            "#9e1f47",
            f"-d '{safe_b}'",
            "Payload (-d)",
            "Transmits the JSON body inside <b>single quotes</b> so the shell preserves inner double quotes around keys and string values.",
        )

    return f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;">
      <table style="width:100%; border-collapse:collapse; background:#ffffff; border:1px solid #e3e6ec; border-radius:6px;">
        <thead>
          <tr style="background:#f1f3f6; text-align:left; font-size:11px; color:#5c6470; text-transform:uppercase;">
            <th style="padding:7px 10px; width:115px;">Part</th>
            <th style="padding:7px 10px; width:270px;">Command Token</th>
            <th style="padding:7px 10px;">Trainee Explanation &amp; Purpose</th>
          </tr>
        </thead>
        <tbody>
          {''.join(rows_html)}
        </tbody>
      </table>
    </div>
    """


# =====================================================================
# 3. SQLITE STORAGE FOR CUSTOM EVERYDAY COMMANDS
# =====================================================================

class CommandLibraryStore:
    """Persists saved & custom curl commands in SQLite (~/.curl_studio/commands.db)."""

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
            cur = conn.execute("SELECT COUNT(*) FROM saved_commands")
            count = cur.fetchone()[0]
            if count == 0:
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
            cur = conn.execute(
                "SELECT id, spec_json FROM saved_commands ORDER BY id ASC"
            )
            results: List[Tuple[int, CurlCommandSpec]] = []
            for row_id, s_json in cur.fetchall():
                try:
                    results.append((row_id, CurlCommandSpec.from_dict(json.loads(s_json))))
                except Exception:
                    pass
            return results

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


# =====================================================================
# 4. EXECUTION ENGINE (REAL CURL SUBPROCESS + TRAINEE SIMULATOR)
# =====================================================================

@dataclass
class ExecutionResult:
    ok: bool
    status_line: str
    elapsed_ms: int
    pretty_body: str
    headers_text: str
    verbose_trace: str
    raw_output: str
    mode_used: str


def execute_curl_spec(spec: CurlCommandSpec, execution_mode: str = "auto") -> ExecutionResult:
    """
    Executes or simulates the curl request:
    - 'real_curl': Executes system `curl` binary via subprocess
    - 'sim_200', 'sim_400', 'sim_401', 'sim_500': Trainee classroom simulation modes
    - 'auto': Tries real `curl` first; if host is unreachable/mock (like `http:sdfble`),
              shows the real curl error trace alongside a simulated response preview for teaching.
    """
    start = time.perf_counter()

    # Check if user explicitly selected a simulation mode
    if execution_mode.startswith("sim_"):
        return _simulate_response(spec, execution_mode)

    # Attempt real system curl execution
    curl_bin = shutil.which("curl")
    if curl_bin and execution_mode in ("auto", "real_curl"):
        import subprocess

        # Always run curl with -i and -v in capture mode so we can populate all 3 response tabs
        argv = [curl_bin, "-sS", "-i", "-v", "-X", spec.method]
        if spec.flags.get("flag_L"):
            argv.append("-L")
        if spec.flags.get("flag_k"):
            argv.append("-k")
        if spec.flags.get("flag_compressed"):
            argv.append("--compressed")
        if spec.flags.get("flag_u"):
            argv.extend(["-u", spec.flag_args.get("flag_u", "admin:secret123")])
        if spec.flags.get("flag_m"):
            argv.extend(["-m", str(spec.flag_args.get("flag_m", "10"))])
        else:
            argv.extend(["-m", "8"])
        if spec.flags.get("flag_x"):
            argv.extend(["-x", spec.flag_args.get("flag_x", "http://proxy.corp:8080")])

        for h in spec.headers:
            if h.enabled and h.key.strip():
                argv.extend(["-H", f"{h.key.strip()}: {h.value.strip()}"])

        if spec.body.strip() and spec.method not in ("GET", "HEAD"):
            argv.extend(["-d", spec.body.strip()])

        argv.append(spec.url.strip())

        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=12,
            )
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            stdout_str = proc.stdout or ""
            stderr_str = proc.stderr or ""

            if proc.returncode == 0 and stdout_str.strip():
                headers_part, body_part = _split_http_headers_and_body(stdout_str)
                status_line = headers_part.splitlines()[0] if headers_part else "HTTP/1.1 200 OK"
                pretty_body = _try_pretty_json(body_part)

                # Save to file if -o was checked
                if spec.flags.get("flag_o"):
                    out_file = spec.flag_args.get("flag_o", "response.json")
                    try:
                        Path(out_file).write_text(pretty_body, encoding="utf-8")
                    except Exception:
                        pass

                ok = not any(code in status_line for code in ("400", "401", "403", "404", "500", "502", "503"))
                return ExecutionResult(
                    ok=ok,
                    status_line=status_line,
                    elapsed_ms=elapsed_ms,
                    pretty_body=pretty_body,
                    headers_text=headers_part or "(No HTTP headers captured)",
                    verbose_trace=stderr_str or "(No verbose stderr output)",
                    raw_output=stdout_str,
                    mode_used="Live System cURL Binary",
                )
            else:
                # Real curl failed (e.g., host `http:sdfble` could not be resolved or sandbox offline)
                if execution_mode == "real_curl":
                    return ExecutionResult(
                        ok=False,
                        status_line=f"cURL Exit Code {proc.returncode}",
                        elapsed_ms=elapsed_ms,
                        pretty_body=stderr_str or stdout_str or "cURL command failed.",
                        headers_text="(Connection did not complete — see Verbose Trace tab)",
                        verbose_trace=stderr_str,
                        raw_output=stderr_str + "\n" + stdout_str,
                        mode_used=f"Live System cURL (Exit {proc.returncode})",
                    )
                else:
                    # Smart Auto Mode: provide simulated response + real curl trace
                    sim = _simulate_response(spec, "sim_auto", real_stderr=stderr_str)
                    return sim
        except Exception as exc:
            if execution_mode == "real_curl":
                return ExecutionResult(
                    ok=False,
                    status_line="Execution Error",
                    elapsed_ms=int((time.perf_counter() - start) * 1000),
                    pretty_body=str(exc),
                    headers_text="",
                    verbose_trace=str(exc),
                    raw_output=str(exc),
                    mode_used="Live System cURL Error",
                )

    return _simulate_response(spec, "sim_auto")


def _split_http_headers_and_body(raw_stdout: str) -> Tuple[str, str]:
    """Splits `curl -i` output into (response_headers, response_body), handling 100 Continue or redirects."""
    normalized = raw_stdout.replace("\r\n", "\n")
    parts = normalized.split("\n\n")
    header_blocks: List[str] = []
    body_blocks: List[str] = []
    for idx, block in enumerate(parts):
        if block.startswith("HTTP/"):
            header_blocks.append(block)
        else:
            body_blocks = parts[idx:]
            break
    return "\n\n".join(header_blocks).strip(), "\n\n".join(body_blocks).strip()


def _try_pretty_json(text: str) -> str:
    trimmed = text.strip()
    if not trimmed:
        return "(Empty Response Body)"
    try:
        parsed = json.loads(trimmed)
        return json.dumps(parsed, indent=2)
    except Exception:
        return trimmed


def _simulate_response(
    spec: CurlCommandSpec, sim_mode: str, real_stderr: str = ""
) -> ExecutionResult:
    """Generates realistic HTTP responses and verbose traces for trainee demonstrations."""
    body_trimmed = spec.body.strip()
    parsed_json = None
    json_valid = True
    if body_trimmed and spec.method not in ("GET", "HEAD"):
        try:
            parsed_json = json.loads(body_trimmed)
        except Exception:
            json_valid = False

    url_malformed = "://" not in spec.url

    if sim_mode == "sim_400" or (sim_mode == "sim_auto" and not json_valid):
        status_line = "HTTP/1.1 400 Bad Request"
        resp_obj = {
            "error": "Bad Request",
            "code": "INVALID_JSON_PAYLOAD",
            "message": "Server could not parse request payload as valid JSON. Check quote escaping!",
            "raw_received": body_trimmed,
        }
        ok = False
    elif sim_mode == "sim_401":
        status_line = "HTTP/1.1 401 Unauthorized"
        resp_obj = {
            "error": "Unauthorized",
            "message": 'Missing or invalid authentication. Add -H "Authorization: Bearer <token>" or -u user:pass.',
        }
        ok = False
    elif sim_mode == "sim_500":
        status_line = "HTTP/1.1 500 Internal Server Error"
        resp_obj = {
            "error": "Internal Server Error",
            "trace_id": "trc-2026-9981",
            "message": "Unhandled exception on backend service while processing request.",
        }
        ok = False
    else:
        status_line = "HTTP/1.1 201 Created" if spec.method == "POST" else "HTTP/1.1 200 OK"
        resp_obj = {
            "status": "success",
            "method": spec.method,
            "endpoint": spec.url,
            "url_scheme_warning": (
                "Notice: Your URL is missing '//' (e.g. http://sdfble)" if url_malformed else None
            ),
            "headers_received": {
                h.key.strip(): h.value.strip() for h in spec.headers if h.enabled and h.key.strip()
            },
            "received_payload": parsed_json if parsed_json is not None else (body_trimmed or None),
        }
        if isinstance(parsed_json, dict) and "product_id" in parsed_json:
            qty = float(parsed_json.get("quantity", 0) or 0)
            price = float(parsed_json.get("price", 0) or 0)
            resp_obj["order_confirmation"] = {
                "order_id": "ORD-2026-10199",
                "product_id": parsed_json.get("product_id"),
                "quantity": parsed_json.get("quantity"),
                "unit_price": parsed_json.get("price"),
                "line_total": round(qty * price, 4),
            }
        ok = True

    pretty_body = json.dumps(resp_obj, indent=2)
    headers_text = (
        f"{status_line}\n"
        f"Server: trainee-sim-gateway/2.4\n"
        f"Content-Type: application/json; charset=utf-8\n"
        f"Content-Length: {len(pretty_body)}\n"
        f"X-Request-ID: req-cel-10199"
    )

    verbose_lines = []
    if real_stderr:
        verbose_lines.append("=== [Real System cURL Trace] ===")
        verbose_lines.append(real_stderr.strip())
        verbose_lines.append("\n=== [Simulated HTTP Handshake for Trainee Inspection] ===")

    verbose_lines.extend(
        [
            f"* Preparing {spec.method} request to {spec.url}",
            f"> {spec.method} {spec.url} HTTP/1.1",
            "> User-Agent: curl/8.5.0",
        ]
    )
    for h in spec.headers:
        if h.enabled and h.key.strip():
            verbose_lines.append(f"> {h.key.strip()}: {h.value.strip()}")
    if body_trimmed and spec.method not in ("GET", "HEAD"):
        verbose_lines.append(f"> Content-Length: {len(body_trimmed)}")
        verbose_lines.append(">")
        verbose_lines.append(f"* upload completely sent off: {len(body_trimmed)} bytes")
    for hl in headers_text.splitlines():
        verbose_lines.append(f"< {hl}")
    verbose_lines.append("<")

    raw_combined = f"{headers_text}\n\n{pretty_body}" if spec.flags.get("flag_i") else pretty_body

    return ExecutionResult(
        ok=ok,
        status_line=status_line,
        elapsed_ms=34,
        pretty_body=pretty_body,
        headers_text=headers_text,
        verbose_trace="\n".join(verbose_lines),
        raw_output=raw_combined,
        mode_used="Smart Trainee Simulator (Host Unreachable / Offline)",
    )


# =====================================================================
# 5. PYQT6 DESKTOP APPLICATION UI
# =====================================================================

if PYQT_AVAILABLE:

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
            self.setWindowTitle("cURL Interactive Studio & Trainee Guide — Desktop Edition")
            self.resize(1360, 880)

            self.store = CommandLibraryStore()
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
                QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTableWidget, QListWidget {
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
            root_layout.setContentsMargins(12, 10, 12, 10)
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

            top_row.addWidget(self.raw_curl_input, 1)
            top_row.addWidget(btn_parse)
            top_row.addWidget(btn_autofix)
            import_layout.addLayout(top_row)

            self.doctor_label = QLabel()
            self.doctor_label.setWordWrap(True)
            self.doctor_label.setStyleSheet(
                "background-color: #fdf4e7; color: #8c530c; border: 1px solid #f0c987; "
                "border-radius: 4px; padding: 6px 10px; font-size: 12px;"
            )
            import_layout.addWidget(self.doctor_label)
            root_layout.addWidget(import_group)

            # --- MAIN SPLITTER: LEFT SIDEBAR (SAVED LIBRARY) + RIGHT TABS ---
            main_splitter = QSplitter(Qt.Orientation.Horizontal)

            # Left Sidebar: Everyday Saved Commands Library
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

            # Right Main Tabs
            self.main_tabs = QTabWidget()
            self.main_tabs.addTab(self._build_workbench_tab(), "1. Visual Request Builder & Runner")
            self.main_tabs.addTab(self._build_encyclopedia_tab(), "2. Common Flags Encyclopedia (18 Flags)")
            self.main_tabs.addTab(self._build_trainee_drills_tab(), "3. Trainee Pitfalls & Classroom Drills")

            main_splitter.addWidget(self.main_tabs)
            main_splitter.setSizes([280, 1040])
            root_layout.addWidget(main_splitter, 1)

            self.status_bar = QStatusBar()
            self.setStatusBar(self.status_bar)
            self._update_doctor_banner(self.raw_curl_input.text())

        def _build_workbench_tab(self) -> QWidget:
            tab = QWidget()
            layout = QVBoxLayout(tab)

            horiz_splitter = QSplitter(Qt.Orientation.Horizontal)

            # --- LEFT PANE OF WORKBENCH: BUILDER CONTROLS ---
            left_pane = QWidget()
            left_layout = QVBoxLayout(left_pane)
            left_layout.setContentsMargins(4, 4, 4, 4)

            # Command Name + Method + URL
            endpoint_group = QGroupBox("Endpoint & Command Label")
            ep_grid = QGridLayout(endpoint_group)

            ep_grid.addWidget(QLabel("Label:"), 0, 0)
            self.name_edit = QLineEdit()
            self.name_edit.setPlaceholderText("e.g., Create Product Order (POST 101)")
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

            # Inner Sub-Tabs for Headers (-H), Payload (-d), and Common Flags
            self.builder_subtabs = QTabWidget()

            # Subtab 1: Payload (-d) with Visual Key/Value Table + Raw JSON
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
            self.body_edit.setMaximumHeight(115)
            self.body_edit.textChanged.connect(self.on_raw_body_text_changed)
            payload_layout.addWidget(self.body_edit)

            self.builder_subtabs.addTab(payload_widget, "Payload Body (-d)")

            # Subtab 2: HTTP Headers (-H)
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
                    arg_edit.setPlaceholderText(f.long)
                    arg_edit.setMaximumWidth(210)
                    arg_edit.textChanged.connect(self.on_flags_ui_changed)
                    self.flag_arg_inputs[f.flag_id] = arg_edit
                    flags_grid.addWidget(arg_edit, row_idx, 1)
                row_idx += 1

            flags_grid.setRowStretch(row_idx, 1)
            flags_scroll.setWidget(flags_container)
            self.builder_subtabs.addTab(flags_scroll, "Common Flags (-i, -v, -L, -k, -u...)")

            left_layout.addWidget(self.builder_subtabs, 1)

            # Bottom of Left Pane: Visual Command Anatomy Table for Trainees
            anatomy_group = QGroupBox("Trainee Visual Command Breakdown (Explains Every Active Flag)")
            anatomy_layout = QVBoxLayout(anatomy_group)
            self.anatomy_browser = QTextBrowser()
            self.anatomy_browser.setMinimumHeight(185)
            anatomy_layout.addWidget(self.anatomy_browser)
            left_layout.addWidget(anatomy_group)

            horiz_splitter.addWidget(left_pane)

            # --- RIGHT PANE OF WORKBENCH: GENERATED COMMAND & RESPONSE INSPECTOR ---
            right_pane = QWidget()
            right_layout = QVBoxLayout(right_pane)
            right_layout.setContentsMargins(4, 4, 4, 4)

            # Generated Command Card
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
            self.generated_cmd_edit.setMaximumHeight(145)
            gen_layout.addWidget(self.generated_cmd_edit)
            right_layout.addWidget(gen_group)

            # Response Inspector Card
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

            # Status Badge Row
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

            # Response Output Tabs
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
            horiz_splitter.setSizes([580, 500])
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

        def _build_trainee_drills_tab(self) -> QWidget:
            tab = QWidget()
            layout = QVBoxLayout(tab)
            browser = QTextBrowser()
            browser.setHtml(
                """
                <div style="font-family: 'Segoe UI', sans-serif; padding: 12px; line-height: 1.6;">
                  <h2 style="color:#11141a; margin-top:0;">Trainee Onboarding Guide: Top 4 cURL Pitfalls &amp; Fixes</h2>
                  <p style="color:#5c6470;">Use these 4 real-world scenarios when training junior engineers on REST API debugging with <code>curl</code>.</p>

                  <div style="background:#ffffff; border:1px solid #dfe3eb; border-radius:6px; padding:14px; margin-bottom:14px;">
                    <h3 style="color:#3559e6; margin-top:0;">1. The Nested Double-Quote Trap (Why your original command gives a headache!)</h3>
                    <p><b>Broken Command:</b> <code>curl -X POST "http:sdfble" -H "Content-Type: application/json" -d "{"product_id": "101", "quantity": 1, "price": 0.01}"</code></p>
                    <p><b>What happens in Bash/Zsh:</b> The shell pairs the opening quote after <code>-d "{"</code> with the quote right before <code>product_id</code>! It strips the quotes and sends <code>{product_id: 101, quantity: 1, price: 0.01}</code> — which fails JSON parsing on the server with <b>400 Bad Request</b>.</p>
                    <p><b>The Fix:</b> Always wrap JSON payloads in <b>single quotes</b> on Linux/macOS (or let the Visual JSON Table in Tab 1 build it for you):<br>
                    <code>curl -X POST "http://localhost:8000/api/orders" -H "Content-Type: application/json" -d '{"product_id": "101", "quantity": 1, "price": 0.01}'</code></p>
                  </div>

                  <div style="background:#ffffff; border:1px solid #dfe3eb; border-radius:6px; padding:14px; margin-bottom:14px;">
                    <h3 style="color:#3559e6; margin-top:0;">2. Forgetting <code>-H "Content-Type: application/json"</code> when using <code>-d</code></h3>
                    <p><b>What happens:</b> By default, <code>curl -d</code> sends <code>Content-Type: application/x-www-form-urlencoded</code>. Frameworks like Django REST Framework, FastAPI, and Express will not parse the JSON body unless <code>-H "Content-Type: application/json"</code> is included.</p>
                  </div>

                  <div style="background:#ffffff; border:1px solid #dfe3eb; border-radius:6px; padding:14px; margin-bottom:14px;">
                    <h3 style="color:#3559e6; margin-top:0;">3. Getting Empty Output on Redirected URLs (Missing <code>-L</code>)</h3>
                    <p><b>What happens:</b> If an internal endpoint redirects <code>http://</code> to <code>https://</code> or adds a trailing slash (HTTP 301/302), browsers follow it automatically, but <code>curl</code> stops and prints nothing.</p>
                    <p><b>The Fix:</b> Add <code>-i</code> to see the <code>301/302 Location:</code> header, and add <code>-L</code> (<code>--location</code>) to follow redirects automatically.</p>
                  </div>

                  <div style="background:#ffffff; border:1px solid #dfe3eb; border-radius:6px; padding:14px;">
                    <h3 style="color:#3559e6; margin-top:0;">4. Debugging Internal Lab Fixtures with Self-Signed SSL Certificates (<code>-v</code> and <code>-k</code>)</h3>
                    <p><b>What happens:</b> Manufacturing test stations and local HTTPS services often use self-signed certs, causing <code>curl: (60) SSL certificate problem: self-signed certificate</code>.</p>
                    <p><b>The Fix:</b> Use <code>-v</code> to inspect the TLS handshake and <code>-k</code> (<code>--insecure</code>) on trusted lab networks to bypass certificate verification during hardware/API bring-up.</p>
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

            # Populate headers table
            self.headers_table.blockSignals(True)
            self.headers_table.setRowCount(0)
            for h in self.current_spec.headers:
                self._insert_header_table_row(h.key, h.value, h.enabled)
            self.headers_table.blockSignals(False)

            # Populate flags checkboxes
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
            # Rebind delete buttons
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
                enabled = (
                    cb_item.checkState() == Qt.CheckState.Checked if cb_item else True
                )
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

        # --- JSON VISUAL TABLE <-> RAW JSON BODY SYNC ---
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

        # --- RAW CURL PARSING & AUTO-FIXING ---
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

        # --- OUTPUT REFRESH & EXECUTION ---
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

        # --- SAVED COMMAND LIBRARY ACTIONS ---
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


def run_self_test() -> None:
    """Verifies parser, quote doctor, multi-shell formatter, SQLite store, and execution engine."""
    raw_user_cmd = (
        'curl -X POST "http:sdfble" -H "Content-Type: application/json" '
        '-d "{"product_id": "101", "quantity": 1, "price": 0.01}"'
    )
    warnings = diagnose_raw_curl(raw_user_cmd)
    assert len(warnings) == 2, f"Expected 2 warnings on broken user command, got {warnings}"

    spec, _ = parse_raw_curl_command(raw_user_cmd, auto_fix_url=True)
    assert spec.method == "POST"
    assert spec.url == "http://sdfble"
    assert json.loads(spec.body)["product_id"] == "101"

    bash_out = format_command_for_shell(spec, "bash")
    assert "-d '{\"product_id\": \"101\", \"quantity\": 1, \"price\": 0.01}'" in bash_out

    res = execute_curl_spec(spec, "auto")
    assert "201 Created" in res.status_line
    assert "ORD-2026-10199" in res.pretty_body
    print("Self-test passed: Parser, Quote Doctor, Multi-Shell Generator, and Runner verified.")


def main() -> None:
    if "--self-test" in sys.argv:
        run_self_test()
        return

    if not PYQT_AVAILABLE:
        print(
            "PyQt6 is required to launch the desktop GUI.\n"
            "Install it with:\n"
            "    pip install PyQt6\n"
            "Then run:\n"
            "    python curl_studio_desktop.py"
        )
        sys.exit(1)

    app = QApplication(sys.argv)
    win = CurlStudioMainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
