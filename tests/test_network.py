"""Tests for engine.network: fetch contract, URL policy, retry classification.

Phase 1 (P1.5): redirect final URLs, status classification, retry exhaustion,
retryable/non-retryable errors, and Retry-After.
"""

import socket

import pytest

from engine.network import (
    FetchResult,
    HttpStatusError,
    PrivateAddressError,
    RequestPurpose,
    UrlPolicy,
    UrlPolicyError,
    backoff_seconds,
    canonicalize_url,
    is_retryable_status,
    origin,
    resolve_url,
    retry_after_seconds,
)
from engine.schemas import RetryConfig, UrlPolicyConfig


# ---------------------------------------------------------------- FetchResult

def test_fetch_result_carries_contract_fields():
    """P1.1: a fetch result must expose content, final URL, status, headers,
    elapsed time, attempts, and the request URL."""
    result = FetchResult(
        content="<html></html>",
        requested_url="https://example.com/start",
        final_url="https://example.com/page",
        status_code=200,
        headers={"content-type": "text/html"},
        elapsed_ms=12.5,
        attempts=2,
        redirect_chain=["https://example.com/start", "https://example.com/page"],
    )
    assert result.content == "<html></html>"
    assert result.requested_url == "https://example.com/start"
    assert result.final_url == "https://example.com/page"
    assert result.status_code == 200
    assert result.headers["content-type"] == "text/html"
    assert result.elapsed_ms == 12.5
    assert result.attempts == 2
    assert result.redirect_chain[-1] == result.final_url


def test_fetch_result_defaults():
    result = FetchResult(content="", requested_url="http://x.test", final_url="http://x.test", status_code=200)
    assert result.headers == {}
    assert result.elapsed_ms == 0.0
    assert result.attempts == 1
    assert result.redirect_chain == []
    assert result.error is None
    assert result.ok() is True


def test_fetch_result_error_attached():
    from engine.errors import ErrorCategory, FetchError
    result = FetchResult(
        content="",
        requested_url="http://x.test",
        final_url="http://x.test",
        status_code=503,
        error=FetchError(ErrorCategory.HTTP, "http://x.test", status_code=503),
    )
    assert result.ok() is False
    assert result.error.category == ErrorCategory.HTTP


def test_http_status_error_converts_to_fetch_error():
    from engine.errors import ErrorCategory
    exc = HttpStatusError(503, "https://example.com/")
    fetch_error = exc.to_fetch_error(attempts=3)
    assert fetch_error.category == ErrorCategory.HTTP
    assert fetch_error.status_code == 503
    assert fetch_error.attempts == 3


# ------------------------------------------------------------ canonicalize_url

def test_canonicalize_lowercases_host_and_normalizes_path():
    # Host is lowercased and default port dropped; path is preserved verbatim
    # (dot-segment removal is the resolver's job, not the validator's).
    assert canonicalize_url("HTTP://Example.COM:80/a/../b") == "http://example.com/a/../b"


def test_canonicalize_drops_default_port():
    assert canonicalize_url("https://example.com:443/x") == "https://example.com/x"
    assert canonicalize_url("http://example.com:80/x") == "http://example.com/x"
    assert canonicalize_url("http://example.com:8080/x") == "http://example.com:8080/x"


def test_canonicalize_rejects_embedded_credentials():
    with pytest.raises(UrlPolicyError):
        canonicalize_url("https://user:pass@example.com/")


def test_canonicalize_rejects_missing_scheme_or_host():
    with pytest.raises(UrlPolicyError):
        canonicalize_url("example.com/path")
    with pytest.raises(UrlPolicyError):
        canonicalize_url("https:///no-host")


def test_origin_is_scheme_and_host():
    assert origin("https://a.example.com:8443/x?q=1") == "https://a.example.com:8443"
    assert origin("https://example.com:443/") == "https://example.com"


def test_resolve_url_joins_relative_to_base():
    assert resolve_url("https://example.com/a/page", "../other") == "https://example.com/other"


# -------------------------------------------------------------------- UrlPolicy

@pytest.fixture
def permissive_policy():
    return UrlPolicy(UrlPolicyConfig())


def test_same_origin_allowed(permissive_policy):
    url = permissive_policy.validate("https://example.com/root")
    assert url == "https://example.com/root"


def test_same_origin_nested_within_root(permissive_policy):
    # Same-origin nested URL is fine even though parent differs from a root URL.
    permissive_policy.validate(
        "https://example.com/child", parent_url="https://example.com/root"
    )


def test_cross_origin_denied_without_external_opt_in(permissive_policy):
    with pytest.raises(UrlPolicyError):
        permissive_policy.validate("https://other.com/x", parent_url="https://example.com/root")


def test_external_domain_allowed_when_configured(monkeypatch):
    monkeypatch.setattr(
        "engine.network.socket.getaddrinfo",
        lambda host, port: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))],
    )
    policy = UrlPolicy(UrlPolicyConfig(
        allow_external_urls=True,
        allowed_domains=["allowed.com"],
        allow_subdomains=True,
    ))
    url = policy.validate("https://sub.allowed.com/x", parent_url="https://example.com/root")
    assert url == "https://sub.allowed.com/x"

    with pytest.raises(UrlPolicyError):
        policy.validate("https://notallowed.com/x", parent_url="https://example.com/root")


def test_scheme_restricted_to_http_https():
    policy = UrlPolicy(UrlPolicyConfig())
    with pytest.raises(UrlPolicyError):
        policy.validate("file:///etc/passwd")
    with pytest.raises(UrlPolicyError):
        policy.validate("ftp://example.com/file")


def test_private_network_blocked_by_default():
    policy = UrlPolicy(UrlPolicyConfig())
    for target in [
        "http://localhost:8000/",
        "http://127.0.0.1/",
        "http://10.0.0.1/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",
    ]:
        with pytest.raises(PrivateAddressError):
            policy.validate(target, parent_url="https://example.com/")


def test_private_network_opt_out():
    policy = UrlPolicy(UrlPolicyConfig(block_private_networks=False))
    assert policy.validate("http://127.0.0.1:8000/", parent_url="http://127.0.0.1:8000/") \
        == "http://127.0.0.1:8000/"


# ------------------------------------------------------------- header scoping

def test_headers_scoped_to_origin():
    policy = UrlPolicy(UrlPolicyConfig())
    sensitive = {
        "Authorization": "Bearer abc",
        "Cookie": "session=1",
        "X-Api-Key": "k",
        "X-Custom": "fine",
    }
    # Same origin keeps everything.
    same = policy.headers_for("https://example.com/a", "https://example.com/b", sensitive)
    assert same["Authorization"] == "Bearer abc"
    assert same["Cookie"] == "session=1"
    assert same["X-Api-Key"] == "k"
    # Cross-origin strips sensitive headers, keeps safe ones.
    cross = policy.headers_for("https://other.com/a", "https://example.com/b", sensitive)
    assert "Authorization" not in cross
    assert "Cookie" not in cross
    assert "X-Api-Key" not in cross
    assert cross["X-Custom"] == "fine"


def test_bearer_token_only_added_same_origin():
    policy = UrlPolicy(UrlPolicyConfig())
    same = policy.headers_for("https://example.com/a", "https://example.com/b", {}, bearer_token="tok")
    assert same["Authorization"] == "Bearer tok"
    cross = policy.headers_for("https://other.com/a", "https://example.com/b", {}, bearer_token="tok")
    assert "Authorization" not in cross


def test_request_purpose_enum_values():
    assert RequestPurpose.ROOT.value == "root"
    assert RequestPurpose.PAGINATION.value == "pagination"
    assert RequestPurpose.NESTED.value == "nested"
    assert RequestPurpose.ROBOTS.value == "robots"
    assert RequestPurpose.OAUTH.value == "oauth"


# ------------------------------------------------------------ retry policy

def test_retryable_status_classification():
    config = RetryConfig()
    for status in [408, 425, 429, 500, 502, 503, 504]:
        assert is_retryable_status(status, config), f"{status} should be retryable"
    for status in [200, 301, 400, 401, 403, 404, 405, 410, 422]:
        assert not is_retryable_status(status, config), f"{status} should not be retryable"


def test_custom_retry_statuses():
    config = RetryConfig(retry_statuses=[429])
    assert is_retryable_status(429, config)
    assert not is_retryable_status(500, config)


def test_backoff_bounded_and_growing():
    config = RetryConfig(base_delay_seconds=1.0, max_delay_seconds=30.0)
    # Backoff should stay within the exponential bounds with jitter.
    for attempt in range(1, 6):
        delay = backoff_seconds(attempt, config)
        upper = min(config.base_delay_seconds * (2 ** (attempt - 1)), config.max_delay_seconds) * 1.2
        assert 0.0 <= delay <= upper + 1e-9


def test_retry_after_seconds_format():
    assert retry_after_seconds("30", cap=300) == pytest.approx(30.0)
    assert retry_after_seconds("0", cap=300) == 0.0
    # Negative / past values clamp to zero.
    assert retry_after_seconds("-5", cap=300) == 0.0


def test_retry_after_http_date_format():
    # A date slightly in the future yields a small positive delay.
    from datetime import datetime, timedelta, timezone
    future = datetime.now(timezone.utc) + timedelta(seconds=5)
    stamp = future.strftime("%a, %d %b %Y %H:%M:%S GMT")
    delay = retry_after_seconds(stamp, cap=300)
    assert delay is not None
    assert 0.0 <= delay <= 10.0


def test_retry_after_invalid_returns_none():
    assert retry_after_seconds("not-a-number", cap=300) is None
    assert retry_after_seconds(None, cap=300) is None


def test_retry_after_capped():
    assert retry_after_seconds("999999", cap=300) == 300.0


# ------------------------------------------------- P3.2 allowed_domains wildcards

def test_wildcard_domain_matches_subdomains():
    policy = UrlPolicy(UrlPolicyConfig(
        allow_external_urls=True,
        allowed_domains=["*.example.com"],
    ))
    assert policy.is_allowed_origin("https://a.example.com/x", "https://root.com/")
    assert policy.is_allowed_origin("https://deep.a.example.com/x", "https://root.com/")
    # The bare domain is not matched by the wildcard.
    assert not policy.is_allowed_origin("https://example.com/x", "https://root.com/")


def test_wildcard_requires_allow_external_urls():
    policy = UrlPolicy(UrlPolicyConfig(allowed_domains=["*.example.com"]))
    assert not policy.is_allowed_origin("https://a.example.com/x", "https://root.com/")


def test_allowed_domains_normalized_case_and_dot():
    policy = UrlPolicy(UrlPolicyConfig(
        allow_external_urls=True,
        allowed_domains=["EXAMPLE.com.", "  Sub.Example.org  "],
    ))
    assert policy.is_allowed_origin("https://example.com/x", "https://root.com/")
    assert policy.is_allowed_origin("https://sub.example.org/x", "https://root.com/")


def test_invalid_allowed_domain_rejected_at_schema():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        UrlPolicyConfig(allowed_domains=["example.com/path"])
    with pytest.raises(ValidationError):
        UrlPolicyConfig(allowed_domains=["ex*ample.com"])
    with pytest.raises(ValidationError):
        UrlPolicyConfig(allowed_domains=["example.com:8080"])


def test_port_variant_of_allowed_domain_not_matched():
    policy = UrlPolicy(UrlPolicyConfig(
        allow_external_urls=True,
        allowed_domains=["example.com"],
    ))
    # Port is significant for host matching.
    assert not policy.is_allowed_origin("https://example.com:8080/x", "https://root.com/")


# ------------------------------------------------- P3.4 DNS / SSRF pre-flight

def test_hostname_resolving_to_private_rejected(monkeypatch):
    monkeypatch.setattr(
        "engine.network.socket.getaddrinfo",
        lambda host, port: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))],
    )
    policy = UrlPolicy(UrlPolicyConfig())
    with pytest.raises(PrivateAddressError):
        policy.validate("http://evil.internal/x", parent_url="https://example.com/")


def test_hostname_resolving_to_public_allowed(monkeypatch):
    monkeypatch.setattr(
        "engine.network.socket.getaddrinfo",
        lambda host, port: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))],
    )
    policy = UrlPolicy(UrlPolicyConfig())
    assert policy.validate("http://example.com/x", parent_url="http://example.com/") \
        == "http://example.com/x"


def test_resolution_error_permissive_with_log(monkeypatch):
    def _raise(host, port):
        raise socket.gaierror("no such host")
    monkeypatch.setattr("engine.network.socket.getaddrinfo", _raise)
    policy = UrlPolicy(UrlPolicyConfig())
    # Documented residual risk: unresolved hosts are allowed.
    assert policy.validate("http://nxdomain.invalid/x", parent_url="http://nxdomain.invalid/") \
        == "http://nxdomain.invalid/x"


def test_resolve_dns_false_skips_dns(monkeypatch):
    called = []

    def _fake(host, port):
        called.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]
    monkeypatch.setattr("engine.network.socket.getaddrinfo", _fake)
    policy = UrlPolicy(UrlPolicyConfig(resolve_dns=False))
    # Private-resolving hostname passes because DNS pre-flight is off.
    assert policy.validate("http://evil.internal/x", parent_url="http://evil.internal/") \
        == "http://evil.internal/x"
    assert called == []


def test_ipv6_private_resolved_rejected(monkeypatch):
    monkeypatch.setattr(
        "engine.network.socket.getaddrinfo",
        lambda host, port: [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("fc00::1", 0))],
    )
    policy = UrlPolicy(UrlPolicyConfig())
    with pytest.raises(PrivateAddressError):
        policy.validate("http://ipv6.internal/x", parent_url="https://example.com/")


# ------------------------------------------------- P3.5 header scoping hardening

def test_sensitive_header_mixed_case_stripped():
    policy = UrlPolicy(UrlPolicyConfig())
    cross = policy.headers_for(
        "https://other.com/a",
        "https://example.com/b",
        {"AUTHORIZATION": "Bearer x", "X-Custom": "ok"},
    )
    assert "AUTHORIZATION" not in cross
    assert "authorization" not in cross
    assert cross["X-Custom"] == "ok"


def test_cookie_header_stripped_cross_origin():
    policy = UrlPolicy(UrlPolicyConfig())
    cross = policy.headers_for(
        "https://other.com/a",
        "https://example.com/b",
        {"Cookie": "session=1", "cookie": "session=2"},
    )
    assert "Cookie" not in cross
    assert "cookie" not in cross
