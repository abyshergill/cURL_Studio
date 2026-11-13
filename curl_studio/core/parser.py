"""Raw cURL command parser and Trainee Quote/Syntax Doctor."""

from __future__ import annotations
import re
import shlex
from typing import List, Optional, Tuple
from .models import CurlCommandSpec, HeaderItem


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
            'Nested Double-Quote Trap: Wrapping JSON in double quotes (-d "{"product_id": "101"}") '
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
    has_json_header = bool(re.search(r"application/json", text, re.IGNORECASE))
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
        cleaned_raw = (
            raw[: broken_json_match.start()]
            + "-d __BROKEN_JSON_PLACEHOLDER__"
            + raw[broken_json_match.end() :]
        )

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
