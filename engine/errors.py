"""Unified fetch-error taxonomy for the Glider engine.

The engine previously raised ad-hoc exceptions (UrlPolicyError, HttpStatusError,
ResolverParseError, bare RuntimeError) that callers could not distinguish. This
module defines ONE authoritative classification: an ``ErrorCategory`` enum, a
``FetchError`` exception carrying retry context, and ``classify_exception`` which
maps transport/library exceptions to categories.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional


class ErrorCategory(str, Enum):
    NETWORK = "network_error"       # transport failure: connection refused/reset, TLS, DNS
    TIMEOUT = "timeout"             # request timed out
    HTTP = "http_error"             # non-2xx final status
    PARSE = "parse_error"           # resolver failed to parse the body
    ROBOTS = "robots_blocked"       # robots.txt disallows the URL
    AUTH = "auth_error"             # token acquisition/refresh failed
    RATE_LIMIT = "rate_limit"       # 429/503 with Retry-After at max attempts
    POLICY = "url_policy_blocked"   # SSRF/URL policy refused the request
    VALIDATION = "validation_error"  # extraction validation failed (P6.2)
    NESTED = "nested_error"         # required child extraction failed
    INTERACTION = "interaction_error"  # required browser interaction failed
    INTERNAL = "internal_error"     # programmer error / unexpected exception


# Categories that must NEVER be retried (a retry cannot heal them).
NON_RETRYABLE_CATEGORIES = frozenset(
     {ErrorCategory.PARSE, ErrorCategory.ROBOTS, ErrorCategory.AUTH,
     ErrorCategory.POLICY, ErrorCategory.VALIDATION, ErrorCategory.INTERNAL,
     ErrorCategory.INTERACTION}
)


class FetchError(Exception):
    """A classified fetch failure.

    Carries enough context to drive retry, stats, and checkpoint behaviour.
    """

    def __init__(
        self,
        category: ErrorCategory,
        url: str,
        message: str = "",
        *,
        status_code: Optional[int] = None,
        retry_after: Optional[float] = None,
        cause: Optional[BaseException] = None,
        attempts: int = 1,
        elapsed_ms: float = 0.0,
    ) -> None:
        self.category = category
        self.url = url
        self.status_code = status_code
        self.retry_after = retry_after
        self.cause = cause
        self.attempts = attempts
        self.elapsed_ms = elapsed_ms
        super().__init__(message or f"{category.value} for {url}")

    @property
    def retryable(self) -> bool:
        """True only for categories the retry loop may retry.

        NETWORK/TIMEOUT are always retryable; HTTP only when the status is
        configured as transient; RATE_LIMIT is retryable (respecting the
        Retry-After cap). PARSE/ROBOTS/AUTH/POLICY/INTERNAL never retry.
        """
        if self.category in NON_RETRYABLE_CATEGORIES:
            return False
        if self.category == ErrorCategory.HTTP:
            from engine.network import is_retryable_status
            from engine.schemas import RetryConfig
            return is_retryable_status(self.status_code or 0, RetryConfig())
        return True


class AuthError(FetchError):
    """Token acquisition or refresh failed. Never retried."""

    def __init__(self, url: str, message: str = "", *, cause: Optional[BaseException] = None):
        super().__init__(
            ErrorCategory.AUTH, url, message or "authentication failed", cause=cause
        )


# Transport exception -> category registry. Referenced lazily so importing this
# module never forces curl_cffi/playwright to load.
def _curl_timeout_codes():
    try:
        from curl_cffi.const import CurlECode
        return {CurlECode.OPERATION_TIMEDOUT, getattr(CurlECode, "FTP_ACCEPT_TIMEOUT", 0)}
    except Exception:
        return set()


def classify_exception(exc: BaseException) -> ErrorCategory:
    """Map a transport/library exception to an ErrorCategory."""
    from engine.network import HttpStatusError, NetworkPolicyError, UrlPolicyError

    if isinstance(exc, FetchError):
        return exc.category
    if isinstance(exc, HttpStatusError):
        return ErrorCategory.HTTP
    if isinstance(exc, (UrlPolicyError, NetworkPolicyError)):
        return ErrorCategory.POLICY

    # Resolver parse failure
    try:
        from engine.resolver import ResolverParseError
        if isinstance(exc, ResolverParseError):
            return ErrorCategory.PARSE
    except Exception:
        pass

    # JSON decode failure (JsonResolver wraps in ResolverParseError, but be safe)
    if isinstance(exc, ValueError):
        import json
        if isinstance(exc, json.JSONDecodeError):
            return ErrorCategory.PARSE

    # curl_cffi: single CurlError class with an error code
    try:
        from curl_cffi.requests.errors import CurlError
        if isinstance(exc, CurlError):
            code = getattr(exc, "code", None)
            try:
                from curl_cffi.const import CurlECode
                if code in _curl_timeout_codes():
                    return ErrorCategory.TIMEOUT
            except Exception:
                pass
            return ErrorCategory.NETWORK
    except Exception:
        pass

    # asyncio.TimeoutError (used for request_timeout wrapping)
    import asyncio
    if isinstance(exc, asyncio.TimeoutError):
        return ErrorCategory.TIMEOUT

    # Playwright timeout
    try:
        from playwright._impl._errors import TimeoutError as PlaywrightTimeoutError
        if isinstance(exc, PlaywrightTimeoutError):
            return ErrorCategory.TIMEOUT
    except Exception:
        pass

    # Generic OSError / socket errors -> network
    if isinstance(exc, OSError):
        return ErrorCategory.NETWORK

    return ErrorCategory.INTERNAL
