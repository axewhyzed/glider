"""Tests for engine.errors: the unified fetch-error taxonomy (P1.2)."""

import pytest

from engine.errors import (
    ErrorCategory,
    FetchError,
    NON_RETRYABLE_CATEGORIES,
    classify_exception,
)
from engine.network import HttpStatusError, PrivateAddressError, UrlPolicyError


def test_classify_http_status_error_is_http():
    exc = HttpStatusError(503, "https://example.com/")
    assert classify_exception(exc) == ErrorCategory.HTTP


def test_classify_url_policy_is_policy():
    assert classify_exception(UrlPolicyError("blocked")) == ErrorCategory.POLICY
    assert classify_exception(PrivateAddressError("private")) == ErrorCategory.POLICY


def test_classify_resolver_parse_is_parse():
    from engine.resolver import ResolverParseError
    assert classify_exception(ResolverParseError("bad json")) == ErrorCategory.PARSE


def test_classify_json_decode_is_parse():
    import json
    assert classify_exception(json.JSONDecodeError("x", "doc", 0)) == ErrorCategory.PARSE


def test_classify_asyncio_timeout_is_timeout():
    import asyncio
    assert classify_exception(asyncio.TimeoutError()) == ErrorCategory.TIMEOUT


def test_classify_oserror_is_network():
    assert classify_exception(OSError("connection refused")) == ErrorCategory.NETWORK


def test_classify_curl_timeout_is_timeout():
    from curl_cffi.const import CurlECode
    from curl_cffi.requests.errors import CurlError
    assert classify_exception(CurlError("timed out", CurlECode.OPERATION_TIMEDOUT)) \
        == ErrorCategory.TIMEOUT


def test_classify_curl_connect_is_network():
    from curl_cffi.const import CurlECode
    from curl_cffi.requests.errors import CurlError
    assert classify_exception(CurlError("no route", CurlECode.COULDNT_CONNECT)) \
        == ErrorCategory.NETWORK


def test_classify_unknown_is_internal():
    assert classify_exception(RuntimeError("mystery")) == ErrorCategory.INTERNAL
    assert classify_exception(ValueError("mystery")) == ErrorCategory.INTERNAL


def test_fetch_error_retryable_matrix():
    for category in (ErrorCategory.NETWORK, ErrorCategory.TIMEOUT):
        assert FetchError(category, "u").retryable is True
    for category in NON_RETRYABLE_CATEGORIES:
        assert FetchError(category, "u").retryable is False
    # HTTP retryable only when status is configured transient
    assert FetchError(ErrorCategory.HTTP, "u", status_code=503).retryable is True
    assert FetchError(ErrorCategory.HTTP, "u", status_code=404).retryable is False


def test_fetch_error_carries_context():
    err = FetchError(
        ErrorCategory.RATE_LIMIT,
        "https://example.com/",
        status_code=429,
        retry_after=7.5,
        attempts=3,
    )
    assert err.category == ErrorCategory.RATE_LIMIT
    assert err.status_code == 429
    assert err.retry_after == 7.5
    assert err.attempts == 3
    assert err.retryable is True


def test_fetch_error_message():
    err = FetchError(ErrorCategory.AUTH, "https://example.com/", "token expired")
    assert "token expired" in str(err)
