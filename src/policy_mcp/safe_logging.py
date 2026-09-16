"""Structured operational events with central secret and content redaction."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field

SENSITIVE_KEYS = {
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "dip_api_key",
    "lobbyregister_api_key",
    "genesis_token",
    "eurlex_username",
    "eurlex_password",
}
OMITTED_CONTENT_KEYS = {
    "document_text",
    "personal_record",
    "query_text",
    "response_body",
}
type JsonValue = str | int | float | bool | list[JsonValue] | dict[str, JsonValue] | None


class OperationalEvent(BaseModel):
    """One bounded, non-content operational log event."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    source: str
    route: str
    duration_ms: int = Field(ge=0)
    retry_count: int = Field(ge=0)
    record_count: int = Field(ge=0)
    byte_count: int = Field(ge=0)
    error_code: str | None = None
    details: dict[str, JsonValue]


def _redact_url(value: str, secret_values: set[str]) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"}:
        return value
    hostname = parsed.hostname or ""
    if ":" in hostname:
        hostname = f"[{hostname}]"
    netloc = f"{hostname}:{parsed.port}" if parsed.port is not None else hostname
    safe_query = [
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in SENSITIVE_KEYS
        and not any(fragment in key.lower() for fragment in ("token", "secret", "password"))
    ]
    clean = urlunsplit((parsed.scheme, netloc, parsed.path, urlencode(safe_query), ""))
    for secret in secret_values:
        clean = clean.replace(secret, "[REDACTED]")
    return clean


def _redact(value: Any, secret_values: set[str], *, key: str | None = None) -> Any:
    normalized_key = key.lower() if key else ""
    if normalized_key in OMITTED_CONTENT_KEYS:
        return "[OMITTED]"
    if normalized_key in SENSITIVE_KEYS or any(
        fragment in normalized_key for fragment in ("token", "secret", "password")
    ):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            str(item_key): _redact(item, secret_values, key=str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item, secret_values) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item, secret_values) for item in value)
    if isinstance(value, str):
        if value.startswith(("http://", "https://")):
            return _redact_url(value, secret_values)
        for secret in secret_values:
            value = value.replace(secret, "[REDACTED]")
    return value


def redact_event(event: OperationalEvent, *, secret_values: set[str]) -> OperationalEvent:
    """Return a copy safe to serialize to stderr, files, or debug reports."""
    return event.model_copy(
        update={"details": _redact(event.details, secret_values)},
    )
