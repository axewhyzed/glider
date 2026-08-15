"""Browser-manager unit tests with mocked Playwright objects (P5.1-P5.4).

These never launch a real browser; live-browser tests are gated by the
``browser`` marker in tests/conftest.py.
"""

import asyncio

import pytest

from engine.browser import BrowserManager
from engine.schemas import BrowserConfig, ScraperConfig


def _make_manager(proxy_rotation="per_context", ignore_https_errors=False,
                  context_max_requests=5):
    config = ScraperConfig(
        name="browser_test",
        base_url="https://example.com",
        fields=[],
        use_playwright=True,
        browser=BrowserConfig(
            ignore_https_errors=ignore_https_errors,
            context_max_requests=context_max_requests,
            proxy_rotation=proxy_rotation,
        ),
    )
    return BrowserManager(config)


# ------------------------------------------------------------------- P5.1

def test_ignore_https_errors_defaults_false():
    assert BrowserConfig().ignore_https_errors is False


def test_context_options_carry_ignore_https_errors():
    manager = _make_manager(ignore_https_errors=True)
    options = manager._build_context_options()
    assert options["ignore_https_errors"] is True
    manager2 = _make_manager()
    assert manager2._build_context_options()["ignore_https_errors"] is False


def test_context_options_include_proxy():
    manager = _make_manager()
    options = manager._build_context_options(proxy="http://proxy:8080")
    assert options["proxy"] == {"server": "http://proxy:8080"}


# ------------------------------------------------------------------- P5.2

class FakePage:
    def __init__(self, url=""):
        self.closed = False
        self.url = url

    async def close(self):
        self.closed = True

    async def add_init_script(self, script=None, **kwargs):
        pass

    async def set_extra_http_headers(self, headers):
        pass

    async def goto(self, url, **kwargs):
        return None

    async def content(self):
        return "<html></html>"


class FakeContext:
    def __init__(self):
        self.closed = False
        self.pages = []

    async def new_page(self):
        page = FakePage()
        self.pages.append(page)
        return page

    async def close(self):
        self.closed = True

    async def add_cookies(self, cookies):
        pass

    async def route(self, pattern, handler):
        pass


class FakeBrowser:
    def __init__(self):
        self.contexts = []

    async def new_context(self, **kwargs):
        ctx = FakeContext()
        self.contexts.append(ctx)
        return ctx

    async def close(self):
        pass


def test_active_requests_balanced_after_fetches(monkeypatch):
    manager = _make_manager()
    manager.browser = FakeBrowser()
    manager.context = FakeContext()
    manager.request_count = 0
    manager._active_requests = 0

    async def run():
        for _ in range(3):
            await manager.fetch_page("https://example.com/")
        return manager._active_requests

    count = asyncio.run(run())
    assert count == 0


def test_page_creation_failure_does_not_leak_count(monkeypatch):
    manager = _make_manager()
    manager.browser = FakeBrowser()
    manager.context = FakeContext()

    async def boom_new_page():
        raise RuntimeError("no pages")

    monkeypatch.setattr(manager.context, "new_page", boom_new_page)
    manager._active_requests = 0

    async def run():
        with pytest.raises(RuntimeError):
            await manager.fetch_page("https://example.com/")
        return manager._active_requests

    count = asyncio.run(run())
    assert count == 0


# ------------------------------------------------------------------- P5.3

def test_per_request_proxy_uses_fresh_context(monkeypatch):
    manager = _make_manager(proxy_rotation="per_request")
    manager.browser = FakeBrowser()
    manager.context = FakeContext()

    async def run():
        await manager.fetch_page("https://example.com/a", proxy="http://p1")
        await manager.fetch_page("https://example.com/b", proxy="http://p2")
        return manager.browser.contexts

    contexts = asyncio.run(run())
    assert len(contexts) == 2  # two throwaway contexts


# ------------------------------------------------------------------- P5.4

def test_close_idempotent():
    manager = _make_manager()
    manager.browser = FakeBrowser()
    manager.context = FakeContext()

    async def run():
        await manager.close()
        await manager.close()

    asyncio.run(run())
    assert manager.context is None


def test_cancel_during_fetch_closes_page(monkeypatch):
    manager = _make_manager()
    manager.browser = FakeBrowser()
    manager.context = FakeContext()
    manager._active_requests = 0

    async def cancel_goto(self, url, **kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(FakePage, "goto", cancel_goto)

    async def run():
        with pytest.raises(asyncio.CancelledError):
            await manager.fetch_page("https://example.com/")
        # The page created for this request was closed.
        return manager.context.pages[0].closed

    page_closed = asyncio.run(run())
    assert page_closed is True
    assert manager._active_requests == 0
