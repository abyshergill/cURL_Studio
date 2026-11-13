"""Multi-shell command generator (Bash, One-Liner, Windows CMD, PowerShell, Python requests) and HTML anatomy builder."""

from __future__ import annotations
import json
from typing import List
from .models import CurlCommandSpec
from .flags_db import CURL_FLAGS_DB


def build_curl_argv(spec: CurlCommandSpec, include_writeout: bool = False) -> List[str]:
    """Builds the exact OS argument list for subprocess execution."""
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
