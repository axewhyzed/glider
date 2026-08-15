"""Focused transport and browser-policy regression tests."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from engine.browser import BrowserManager
from engine.errors import AuthError
from engine.network import UrlPolicyError, UrlPolicy
from engine.redact import REDACTED, redact_dict
from engine.schemas import AuthConfig, BrowserConfig, ScraperConfig, UrlPolicyConfig
from engine.scraper import ScraperEngine


def _config(**overrides) -> ScraperConfig:
    values = {
        "name": "luna-transport",
        "base_url": "https://example.com/start",
        "fields": [],
        "use_playwright": True,
        "url_policy": UrlPolicyConfig(resolve_dns=False),
    }
    values.update(overrides)
    return ScraperConfig(**values)


class _FakePage:
    def __init__(self) -> None:
        self.closed = False
        self.url = "https://example.com/start"

    async def close(self) -> None:
        self.closed = True

    async def add_init_script(self, script=None, **kwargs) -> None:
        pass

    async def goto(self, url, **kwargs):
        self.url = url
        return None

    async def content(self) -> str:
        return "<html><body>ok</body></html>"

    async def set_extra_http_headers(self, headers) -> None:
        pass


class _FakeContext:
    def __init__(self, *, cookie_error: bool = False) -> None:
        self.closed = False
        self.cookie_error = cookie_error
        self.cookies = []
        self.pages = []

    async def add_cookies(self, cookies) -> None:
        if self.cookie_error:
            raise RuntimeError("cookie rejected")
        self.cookies.extend(cookies)

    async def route(self, pattern, handler) -> None:
        pass

    async def new_page(self):
        page = _FakePage()
        self.pages.append(page)
        return page

    async def close(self) -> None:
        self.closed = True


class _FakeBrowser:
    def __init__(self, *, cookie_error: bool = False) -> None:
        self.contexts = []
        self.cookie_error = cookie_error

    async def new_context(self, **options):
        context = _FakeContext(cookie_error=self.cookie_error)
        context.options = options
        self.contexts.append(context)
        return context


def test_browser_context_blocks_service_workers_and_direct_unsafe_urls():
    manager = BrowserManager(_config())

    assert manager._build_context_options()["service_workers"] == "block"

    with pytest.raises(UrlPolicyError):
        # Validation occurs before browser/context access.
        import asyncio
        asyncio.run(manager.fetch_page("ftp://example.com/private"))

    data_url = "data:text/html,<html><body>offline</body></html>"
    assert manager._validate_navigation_url(data_url) == data_url
    parameterized_data_url = "data:text/html;charset=utf-8,<html></html>"
    assert manager._validate_navigation_url(parameterized_data_url) == parameterized_data_url
    with pytest.raises(ValueError):
        manager._validate_navigation_url("data:image/svg+xml,<svg></svg>")
    with pytest.raises(ValueError):
        manager._validate_navigation_url("data:text/htmlsomething,<html></html>")


def test_browser_post_is_rejected_before_page_navigation():
    config = _config(use_playwright=False)
    manager = BrowserManager(config)
    manager.browser = _FakeBrowser()

    with pytest.raises(ValueError, match="only GET"):
        import asyncio
        asyncio.run(manager.fetch_page("https://example.com/", method="POST", body={"x": 1}))


def test_browser_post_is_rejected_by_config_validation():
    with pytest.raises(ValidationError, match="use_playwright supports only GET"):
        _config(request_method="POST")


@pytest.mark.asyncio
async def test_per_request_context_receives_scoped_cookies_and_closes(tmp_path):
    cookie_file = tmp_path / "cookies.json"
    cookie_file.write_text(json.dumps({"session": "secret"}), encoding="utf-8")
    manager = BrowserManager(
        _config(
            cookies_file=str(cookie_file),
            browser=BrowserConfig(proxy_rotation="per_request"),
        )
    )
    manager.browser = _FakeBrowser()

    result = await manager.fetch_page("https://example.com/page", proxy="http://proxy.example:8080")

    assert result.status_code == 200
    assert len(manager.browser.contexts) == 1
    context = manager.browser.contexts[0]
    assert context.closed is True
    assert context.cookies[0]["name"] == "session"
    assert context.cookies[0]["url"] == "https://example.com/start"
    assert context.options["service_workers"] == "block"


@pytest.mark.asyncio
async def test_cookie_setup_closes_failed_candidate_and_preserves_shared_context(tmp_path):
    cookie_file = tmp_path / "cookies.json"
    cookie_file.write_text(json.dumps({"session": "secret"}), encoding="utf-8")
    manager = BrowserManager(_config(cookies_file=str(cookie_file)))
    manager.browser = _FakeBrowser(cookie_error=True)
    old_context = _FakeContext()
    manager.context = old_context

    with pytest.raises(RuntimeError, match="cookie rejected"):
        await manager._create_context()

    assert len(manager.browser.contexts) == 1
    assert manager.browser.contexts[0].closed is True
    assert manager.context is old_context
    assert old_context.closed is False


class _TokenResponse:
    def __init__(self, status_code=200, headers=None):
        self.status_code = status_code
        self.headers = headers or {}
        self.text = ""

    def json(self):
        return {"access_token": "token", "expires_in": 3600}


class _TokenSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def _oauth_engine(response):
    config = ScraperConfig(
        name="oauth-transport",
        base_url="https://example.com",
        fields=[],
        url_policy=UrlPolicyConfig(resolve_dns=False),
        request_timeout=7,
        authentication=AuthConfig(
            type="oauth_password",
            token_url="https://example.com/oauth/token",
            client_id="client",
            client_secret="secret",
            username="user",
            password="password",
        ),
    )
    engine = ScraperEngine(config)
    session = _TokenSession(response)
    engine.session = session
    return engine, session


@pytest.mark.asyncio
async def test_oauth_token_request_has_timeout_and_no_redirects():
    engine, session = _oauth_engine(_TokenResponse())

    await engine.ensure_active_token()

    kwargs = session.calls[0][1]
    assert kwargs["timeout"] == 7
    assert kwargs["allow_redirects"] is False


@pytest.mark.asyncio
async def test_oauth_redirect_is_rejected_without_following_location():
    engine, session = _oauth_engine(
        _TokenResponse(302, {"location": "https://attacker.example/token"})
    )

    with pytest.raises(AuthError, match="redirects are not permitted"):
        await engine.ensure_active_token()

    assert len(session.calls) == 1


def test_custom_sensitive_headers_and_proxy_credentials_are_redacted():
    policy = UrlPolicy(UrlPolicyConfig(resolve_dns=False, allow_external_urls=True))
    headers = policy.headers_for(
        "https://other.example/page",
        parent_url="https://example.com/start",
        configured={"X-Client-Secret": "secret", "X-Request-ID": "request"},
    )
    assert "X-Client-Secret" not in headers
    assert headers["X-Request-ID"] == "request"

    redacted = redact_dict(
        {
            "headers": {"X-Client-Secret": "secret", "X-Request-ID": "request"},
            "proxies": ["http://user:password@proxy.example:8080"],
        }
    )
    assert redacted["headers"]["X-Client-Secret"] == REDACTED
    assert redacted["headers"]["X-Request-ID"] == REDACTED
    assert "password" not in redacted["proxies"][0]
