"""Data models for cURL flags, request specifications, headers, and execution results."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List


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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "flag_id": self.flag_id,
            "short": self.short,
            "long": self.long,
            "category": self.category,
            "summary": self.summary,
            "detail": self.detail,
            "example": self.example,
            "trainee_tip": self.trainee_tip,
            "toggleable": self.toggleable,
            "has_arg": self.has_arg,
            "default_arg": self.default_arg,
        }


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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "status_line": self.status_line,
            "elapsed_ms": self.elapsed_ms,
            "pretty_body": self.pretty_body,
            "headers_text": self.headers_text,
            "verbose_trace": self.verbose_trace,
            "mode_used": self.mode_used,
        }
