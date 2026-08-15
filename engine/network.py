"""Shared URL, header, response, and retry policy primitives."""

from __future__ import annotations

import ipaddress
import random
import socket
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from enum import Enum
from typing import Dict, Mapping, Optional
from urllib.parse import urljoin, urlsplit, urlunsplit

from engine.schemas import RetryConfig, UrlPolicyConfig


class RequestPurpose(str, Enum):
    ROOT = "root"
    PAGINATION = "pagination"
    NESTED = "nested"
    ROBOTS = "robots"
    OAUTH = "oauth"


@dataclass
class FetchResult:
    content: str
    requested_url: str
    final_url: str
    status_code: int
    headers: Dict[str, str] = field(default_factory=dict)
    elapsed_ms: float = 0.0
    attempts: int = 1
    redirect_chain: list[str] = field(default_factory=list)
    error: Optional["FetchError"] = None

    def ok(self) -> bool:
        """True when the page was fetched successfully (error is None)."""
        return self.error is None


class NetworkPolicyError(RuntimeError):
    """Base class for a request rejected by policy."""


class UrlPolicyError(NetworkPolicyError):
    pass


class PrivateAddressError(UrlPolicyError):
    pass


class HttpStatusError(RuntimeError):
    def __init__(self, status_code: int, url: str, message: str = "") -> None:
        self.status_code = status_code
        self.url = url
        super().__init__(message or f"HTTP status {status_code} for {url}")

    def to_fetch_error(self, attempts: int = 1, retry_after: Optional[float] = None):
        """Convert to a classified FetchError (HTTP category)."""
        from engine.errors import ErrorCategory, FetchError
        return FetchError(
            ErrorCategory.HTTP,
            self.url,
            str(self),
            status_code=self.status_code,
            retry_after=retry_after,
            cause=self,
            attempts=attempts,
        )


SENSITIVE_HEADERS = {
    "authorization",
    "cookie",
    "proxy-authorization",
    "x-api-key",
    "x-auth-token",
    "x-access-token",
}


def canonicalize_url(url: str) -> str:
    parsed = urlsplit(str(url).strip())
    if not parsed.scheme or not parsed.netloc:
        raise UrlPolicyError(f"URL must include a scheme and host: {url}")
    if parsed.username or parsed.password:
        raise UrlPolicyError("URLs containing embedded credentials are not allowed")
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if not hostname:
        raise UrlPolicyError(f"URL has no hostname: {url}")
    scheme = parsed.scheme.lower()
    try:
        port = parsed.port
    except ValueError:
        port = None  # e.g. malformed port; treat as absent
    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    # Rebuild netloc preserving IPv6 brackets.
    if ":" in hostname:
        netloc = f"[{hostname}]"
    else:
        netloc = hostname
    if port and not default_port:
        netloc = f"{netloc}:{port}"
    return urlunsplit((scheme, netloc, parsed.path or "/", parsed.query, ""))


def origin(url: str) -> str:
    parsed = urlsplit(canonicalize_url(url))
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


def _host_is_private(hostname: str) -> bool:
    if hostname.lower() in {"localhost", "localhost.localdomain"}:
        return True
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
    )


def _is_ip_literal(hostname: str) -> bool:
    try:
        ipaddress.ip_address(hostname)
        return True
    except ValueError:
        return False


def _host_resolves_to_private(hostname: str) -> bool:
    """True when ANY resolved address for the hostname is private.

    Resolution errors are permissive (return False): the literal-IP check
    remains the primary guard and DNS rebinding is a documented residual risk.
    """
    try:
        infos = socket.getaddrinfo(hostname, None)
    except OSError:
        return False
    for info in infos:
        address = info[4][0]
        if _host_is_private(address):
            return True
    return False


class UrlPolicy:
    def __init__(self, config: UrlPolicyConfig) -> None:
        self.config = config
        # Normalize once: lowercase, strip trailing dot. Entries may carry a
        # leading "*." wildcard meaning "match this domain and all subdomains".
        self._domains = [
            d.strip().lower().rstrip(".")
            for d in config.allowed_domains
            if d and d.strip()
        ]
        self._patterns = [d for d in self._domains if d.startswith("*.")]
        self._exact = [d for d in self._domains if not d.startswith("*.")]

    def validate(self, url: str, parent_url: Optional[str] = None) -> str:
        canonical = canonicalize_url(url)
        parsed = urlsplit(canonical)
        if parsed.scheme not in self.config.allowed_schemes:
            raise UrlPolicyError(f"URL scheme is not allowed: {parsed.scheme}")
        if self.config.block_private_networks and _host_is_private(parsed.hostname or ""):
            raise PrivateAddressError(f"Private or local address is not allowed: {parsed.hostname}")
        if self.config.resolve_dns and not _is_ip_literal(parsed.hostname or ""):
            if _host_resolves_to_private(parsed.hostname or ""):
                raise PrivateAddressError(
                    f"Hostname resolves to a private address: {parsed.hostname}"
                )
        if parent_url and not self.is_allowed_origin(canonical, parent_url):
            raise UrlPolicyError(f"Cross-origin URL is not allowed: {canonical}")
        return canonical

    def is_allowed_origin(self, candidate: str, parent: str) -> bool:
        candidate_origin = origin(candidate)
        parent_origin = origin(parent)
        if candidate_origin == parent_origin:
            return True
        if not self.config.allow_external_urls:
            return False

        parsed = urlsplit(candidate)
        host = (parsed.hostname or "").lower().rstrip(".")
        # Host:port is significant for exact matching (https://x:8080 != https://x).
        netloc = (parsed.netloc or "").lower().rstrip(".")
        has_explicit_port = parsed.port is not None and not (
            (parsed.scheme == "http" and parsed.port == 80)
            or (parsed.scheme == "https" and parsed.port == 443)
        )
        # Wildcard entries (*.d) always match subdomains, independent of allow_subdomains.
        for pattern in self._patterns:
            suffix = pattern[1:]  # strip "*."
            if host.endswith(suffix) and host != suffix[1:]:
                return True
        for allowed in self._exact:
            # With an explicit port, match host:port exactly; otherwise host.
            match_target = netloc if has_explicit_port else host
            if match_target == allowed:
                return True
            if (not has_explicit_port
                    and self.config.allow_subdomains
                    and host.endswith("." + allowed)):
                return True
        return False

    def headers_for(
        self,
        url: str,
        parent_url: Optional[str],
        configured: Optional[Mapping[str, str]],
        bearer_token: Optional[str] = None,
    ) -> Dict[str, str]:
        headers = {str(k): str(v) for k, v in (configured or {}).items()}
        same_origin = not parent_url or origin(url) == origin(parent_url)
        if not same_origin:
            headers = {k: v for k, v in headers.items() if k.lower() not in SENSITIVE_HEADERS}
        if bearer_token and same_origin:
            headers["Authorization"] = f"Bearer {bearer_token}"
        return headers


def is_retryable_status(status_code: int, config: RetryConfig) -> bool:
    return status_code in config.retry_statuses


def retry_after_seconds(value: Optional[str], cap: float) -> Optional[float]:
    if not value:
        return None
    try:
        return min(max(float(value.strip()), 0.0), cap)
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            delay = (parsed - datetime.now(timezone.utc)).total_seconds()
            return min(max(delay, 0.0), cap)
        except (TypeError, ValueError, OverflowError):
            return None


def backoff_seconds(attempt: int, config: RetryConfig) -> float:
    base = config.base_delay_seconds * (2 ** max(attempt - 1, 0))
    return min(base, config.max_delay_seconds) * random.uniform(0.8, 1.2)


def resolve_url(base_url: str, value: str) -> str:
    return canonicalize_url(urljoin(base_url, value))
