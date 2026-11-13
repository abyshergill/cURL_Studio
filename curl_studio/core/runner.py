"""Live system cURL execution engine and Trainee Response Simulator."""

from __future__ import annotations
import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import List, Tuple
from .models import CurlCommandSpec, ExecutionResult


def execute_curl_spec(spec: CurlCommandSpec, execution_mode: str = "auto") -> ExecutionResult:
    """
    Executes or simulates the curl request:
    - 'real_curl': Executes system `curl` binary via subprocess
    - 'sim_200', 'sim_400', 'sim_401', 'sim_500': Trainee classroom simulation modes
    - 'auto': Tries real `curl` first; if host is unreachable/mock (like `http:sdfble`),
              shows the real curl error trace alongside a simulated response preview for teaching.
    """
    start = time.perf_counter()

    if execution_mode.startswith("sim_"):
        return _simulate_response(spec, execution_mode)

    curl_bin = shutil.which("curl")
    if curl_bin and execution_mode in ("auto", "real_curl"):
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
                    return _simulate_response(spec, "sim_auto", real_stderr=stderr_str)
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

    verbose_lines: List[str] = []
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
