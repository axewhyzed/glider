"""Credential/token redaction for logs, manifests, and failure output (P9.4)."""

from __future__ import annotations

import re
from typing import Any, Dict, Set

REDACTED = "[REDACTED]"

SECRET_KEYS = {
    "authorization", "cookie", "proxy-authorization", "x-api-key",
    "x-auth-token", "x-access-token", "client_secret", "password",
    "access_token", "refresh_token", "api_key", "apikey", "token",
}

# Bearer / Basic / Cookie header values (handles "Bearer <token>").
_HEADER_RE = re.compile(
    r"((?:authorization|cookie|proxy-authorization|x-api-key|x-auth-token"
    r"|x-access-token)\s*[:=]\s*(?:bearer\s+|basic\s+)?)([^\s,;]+)",
    re.IGNORECASE,
)
# key=value / key: value where key is sensitive.
_KEYVALUE_RE = re.compile(
    r"([\"']?(?:client_secret|password|access_token|refresh_token|api_key|apikey)"
    r"[\"']?\s*[:=]\s*[\"']?)([^\"'\s,;]+)",
    re.IGNORECASE,
)
# Query-param style: ?token=... &token=... &api_key=...
_QUERY_RE = re.compile(
    r"([?&](?:token|apikey|api_key|access_token|refresh_token|client_secret|password)=)[^&\s]+",
    re.IGNORECASE,
)
# user:pass@ in URLs
_URL_CRED_RE = re.compile(r"(://)[^/@\s]+@", re.IGNORECASE)


def redact_text(text: str) -> str:
    """Replace known credential patterns with a redaction marker."""
    if not text:
        return text
    text = _HEADER_RE.sub(lambda m: m.group(1) + REDACTED, text)
    text = _KEYVALUE_RE.sub(lambda m: m.group(1) + REDACTED, text)
    text = _QUERY_RE.sub(lambda m: m.group(1) + REDACTED, text)
    text = _URL_CRED_RE.sub(lambda m: m.group(1) + REDACTED + "@", text)
    return text


def redact_dict(data: Dict[str, Any], keys: Set[str] = SECRET_KEYS) -> Dict[str, Any]:
    """Deep-copy redaction for config dicts, headers, and manifest echoes."""
    result: Dict[str, Any] = {}
    for key, value in data.items():
        if str(key).lower() in keys:
            result[key] = REDACTED
        elif isinstance(value, dict):
            result[key] = redact_dict(value, keys)
        elif isinstance(value, list):
            result[key] = [
                redact_dict(item, keys) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            result[key] = redact_text(str(value)) if isinstance(value, str) else value
    return result


def loguru_filter(record) -> bool:
    """loguru filter that mutates the record message to redact secrets."""
    try:
        record["message"] = redact_text(record["message"])
    except Exception:
        pass
    return True
