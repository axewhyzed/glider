"""Origin-scoped cookie loading for HTTP and browser transports."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

from engine.network import canonicalize_url, origin


@dataclass(frozen=True)
class ScopedCookies:
    """Validated cookies restricted to one configured origin."""

    origin: str = ""
    host: str = ""
    pairs: Dict[str, str] = field(default_factory=dict)
    playwright: List[Dict[str, Any]] = field(default_factory=list)
    header_pairs: Dict[str, str] = field(default_factory=dict)

    def header_for(self, url: str) -> Optional[str]:
        if self.header_pairs and self.origin and origin(url) == self.origin:
            return "; ".join(f"{name}={value}" for name, value in self.header_pairs.items())
        return None


def load_scoped_cookies(path: str | Path, scope_url: Optional[str]) -> ScopedCookies:
    """Load a cookie file while enforcing exact configured-origin scope.

    Flat ``{"name": "value"}`` files are assigned to ``scope_url``.
    Playwright-style lists must include a URL on the same origin or a domain
    exactly matching the configured host. Domain-wide and domain-less cookies
    are narrowed to the configured host before browser injection.
    """
    if not scope_url:
        return ScopedCookies()

    scoped_url = canonicalize_url(str(scope_url))
    scoped_origin = origin(scoped_url)
    scoped_host = (urlsplit(scoped_url).hostname or "").lower().rstrip(".")
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    pairs: Dict[str, str] = {}
    header_pairs: Dict[str, str] = {}
    playwright: List[Dict[str, Any]] = []

    def add_cookie(entry: Dict[str, Any], *, include_http_header: bool = True) -> None:
        name = entry.get("name")
        value = entry.get("value")
        if not isinstance(name, str) or not name or not isinstance(value, (str, int, float, bool)):
            return
        pairs[name] = str(value)
        if include_http_header:
            header_pairs[name] = str(value)
        cookie = dict(entry)
        cookie["name"] = name
        cookie["value"] = str(value)
        # ``url`` is the strictest Playwright scope; removing ``domain`` also
        # prevents a supplied parent-domain cookie from crossing hosts.
        cookie.pop("domain", None)
        cookie["url"] = scoped_url
        playwright.append(cookie)

    if isinstance(raw, dict):
        for name, value in raw.items():
            add_cookie({"name": str(name), "value": value})
    elif isinstance(raw, list):
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            candidate = entry.get("url")
            if candidate:
                try:
                    if origin(str(candidate)) != scoped_origin:
                        continue
                except Exception:
                    continue
            else:
                domain = str(entry.get("domain", "")).lstrip(".").lower().rstrip(".")
                if domain != scoped_host:
                    continue
            add_cookie(entry, include_http_header=bool(candidate))

    return ScopedCookies(scoped_origin, scoped_host, pairs, playwright, header_pairs)
