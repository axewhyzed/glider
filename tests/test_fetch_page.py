"""Integration tests for ScraperEngine._fetch_page (P1.3/P1.4).

Drives _fetch_page with a stub AsyncSession injected via engine.session so
retry classification, redirects, and policy failures are deterministic.
"""

import asyncio

import pytest

from engine.errors import ErrorCategory
from engine.network import FetchResult, RequestPurpose
from engine.schemas import RetryConfig, ScraperConfig
from engine.scraper import ScraperEngine


class StubResponse:
    def __init__(self, status_code, text="", headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}


class StubSession:
    """Callable stub: given a callable(sequence) -> response or exception."""

    def __init__(self, responder):
        self.responder = responder
        self.calls = []
        self.headers_seen = []

    async def get(self, url, **kwargs):
        self.calls.append(url)
        self.headers_seen.append(kwargs.get("headers", {}))
        outcome = self.responder(len(self.calls))
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _make_engine(responder, retry: RetryConfig | None = None):
    config = ScraperConfig(
        name="fetch_test",
        base_url="https://example.com",
        fields=[],
        retry=retry or RetryConfig(base_delay_seconds=0.01, max_delay_seconds=0.05),
    )
    engine = ScraperEngine(config)
    engine.session = StubSession(responder)  # type: ignore[assignment]
    return engine


def _ok_response():
    return StubResponse(200, "<html>ok</html>")


# -------------------------------------------------------------- classification

async def test_timeout_classified_as_timeout_not_generic():
    import curl_cffi.requests as curl

    def responder(n):
        raise curl.RequestsError("timed out", code=28)  # CURLE_OPERATION_TIMEDOUT

    engine = _make_engine(responder)
    result = await engine._fetch_page("https://example.com/", purpose=RequestPurpose.ROOT)
    assert result.ok() is False
    assert result.error.category == ErrorCategory.TIMEOUT


async def test_network_error_classified_as_network():
    def responder(n):
        raise OSError("connection refused")

    engine = _make_engine(responder)
    result = await engine._fetch_page("https://example.com/", purpose=RequestPurpose.ROOT)
    assert result.error.category == ErrorCategory.NETWORK


async def test_http_503_retried_then_succeeds():
    def responder(n):
        return StubResponse(503) if n == 1 else _ok_response()

    engine = _make_engine(responder)
    result = await engine._fetch_page("https://example.com/", purpose=RequestPurpose.ROOT)
    assert result.ok() is True
    assert result.status_code == 200
    assert result.attempts == 2
    assert len(engine.session.calls) == 2


async def test_http_503_exhausts_with_http_category():
    def responder(n):
        return StubResponse(503, headers={"retry-after": "1"})

    engine = _make_engine(responder)
    result = await engine._fetch_page("https://example.com/", purpose=RequestPurpose.ROOT)
    assert result.ok() is False
    assert result.error.category == ErrorCategory.HTTP
    assert result.error.status_code == 503
    assert result.attempts == 3  # max_attempts default


async def test_http_429_exhausts_as_rate_limit():
    def responder(n):
        return StubResponse(429, headers={"retry-after": "1"})

    engine = _make_engine(responder)
    result = await engine._fetch_page("https://example.com/", purpose=RequestPurpose.ROOT)
    assert result.ok() is False
    assert result.error.category == ErrorCategory.RATE_LIMIT
    assert result.attempts == 3


async def test_non_retryable_status_never_retried():
    def responder(n):
        return StubResponse(404)

    engine = _make_engine(responder)
    result = await engine._fetch_page("https://example.com/", purpose=RequestPurpose.ROOT)
    assert result.error.category == ErrorCategory.HTTP
    assert result.attempts == 1
    assert len(engine.session.calls) == 1


async def test_cancelled_error_propagates_without_classification():
    def responder(n):
        raise asyncio.CancelledError()

    engine = _make_engine(responder)
    with pytest.raises(asyncio.CancelledError):
        await engine._fetch_page("https://example.com/", purpose=RequestPurpose.ROOT)


# ---------------------------------------------------------------- redirects

async def test_redirect_followed_and_final_url_normalized():
    def responder(n):
        if n == 1:
            return StubResponse(302, headers={"location": "/page2"})
        return StubResponse(200, "<html>page2</html>")

    engine = _make_engine(responder)
    result = await engine._fetch_page("https://example.com/start", purpose=RequestPurpose.ROOT)
    assert result.ok() is True
    assert result.final_url == "https://example.com/page2"
    assert result.redirect_chain[-1] == result.final_url


async def test_redirect_to_private_ip_is_policy_failure():
    def responder(n):
        return StubResponse(302, headers={"location": "http://127.0.0.1/evil"})

    engine = _make_engine(responder)
    result = await engine._fetch_page("https://example.com/", purpose=RequestPurpose.ROOT)
    assert result.ok() is False
    assert result.error.category == ErrorCategory.POLICY
    assert result.attempts == 1
    assert len(engine.session.calls) == 1  # never followed the blocked hop


async def test_redirect_to_cross_origin_denied_when_not_allowed():
    def responder(n):
        return StubResponse(302, headers={"location": "https://evil.com/phish"})

    engine = _make_engine(responder)
    result = await engine._fetch_page("https://example.com/", purpose=RequestPurpose.ROOT)
    assert result.ok() is False
    assert result.error.category == ErrorCategory.POLICY


async def test_redirect_limit_exhausted_is_http_error():
    def responder(n):
        # Self-referential redirect so the chain grows within a single attempt.
        return StubResponse(302, headers={"location": "/loop"})

    engine = _make_engine(responder)
    result = await engine._fetch_page("https://example.com/", purpose=RequestPurpose.ROOT)
    assert result.ok() is False
    # Redirect limit is an HTTP-class failure
    assert result.error.status_code == 302


# ----------------------------------------------------------- attempt metadata

async def test_attempts_recorded_on_success():
    def responder(n):
        return StubResponse(503) if n < 3 else _ok_response()

    engine = _make_engine(responder)
    result = await engine._fetch_page("https://example.com/", purpose=RequestPurpose.ROOT)
    assert result.ok() is True
    assert result.attempts == 3


# ---------------------------------------------------------- auth (P3.6)

async def test_auth_failure_classified_auth_and_not_retried():
    from engine.errors import AuthError
    from engine.schemas import AuthConfig

    config = ScraperConfig(
        name="auth_test",
        base_url="https://example.com",
        fields=[],
        authentication=AuthConfig(
            type="bearer",
            client_secret="static-token",
        ),
        retry=RetryConfig(base_delay_seconds=0.01, max_delay_seconds=0.05),
    )
    engine = ScraperEngine(config)

    async def failing_token():
        raise AuthError("https://auth.example/token", "token endpoint 500")

    engine.ensure_active_token = failing_token  # type: ignore[assignment]
    engine.session = StubSession(lambda n: _ok_response())  # type: ignore[assignment]
    result = await engine._fetch_page("https://example.com/", purpose=RequestPurpose.ROOT)
    assert result.ok() is False
    assert result.error.category == ErrorCategory.AUTH
    assert result.attempts == 1
    assert len(engine.session.calls) == 0  # no fetch attempt made


async def test_oauth_token_url_policy_validated():
    from engine.errors import AuthError
    from engine.schemas import AuthConfig

    config = ScraperConfig(
        name="auth_test",
        base_url="https://example.com",
        fields=[],
        authentication=AuthConfig(
            type="oauth_password",
            token_url="http://127.0.0.1/token",
            client_id="c",
            client_secret="s",
            username="u",
            password="p",
        ),
        retry=RetryConfig(base_delay_seconds=0.01, max_delay_seconds=0.05),
    )
    engine = ScraperEngine(config)
    # Private token_url must be rejected before any network call.
    with pytest.raises(AuthError):
        await engine.ensure_active_token()


# ---------------------------------------------------------- parse (P6.1)

async def test_parse_error_never_retried():
    from engine.errors import FetchError

    def responder(n):
        return StubResponse(200, "{not-json")

    config = ScraperConfig(
        name="json_test",
        base_url="https://example.com",
        response_type="json",
        fields=[],
        retry=RetryConfig(base_delay_seconds=0.01, max_delay_seconds=0.05),
    )
    engine = ScraperEngine(config)
    engine.session = StubSession(responder)  # type: ignore[assignment]
    result = await engine._fetch_page("https://example.com/", purpose=RequestPurpose.ROOT)
    assert result.ok() is True  # transport succeeded; parse is a separate phase
    with pytest.raises(FetchError) as excinfo:
        await engine._process_content(result.content, result.final_url)
    assert excinfo.value.category == ErrorCategory.PARSE
