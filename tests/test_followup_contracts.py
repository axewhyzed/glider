import asyncio
from itertools import cycle
from pathlib import Path

import pytest

from engine.browser import BrowserManager
from engine.checkpoint import CheckpointManager
from engine.errors import ErrorCategory, FetchError
from engine.network import UrlPolicyError, canonicalize_url
from engine.robots import RobotsCache
from engine.schemas import BrowserConfig, InteractionType, ScraperConfig
from engine.scraper import ScraperEngine


def _config(**overrides):
    values = {
        "name": "followup",
        "base_url": "https://example.com",
        "fields": [],
    }
    values.update(overrides)
    return ScraperConfig(**values)


class _FakePage:
    url = "https://example.com/"

    async def add_init_script(self, script=None, **kwargs):
        pass

    async def goto(self, url, **kwargs):
        self.url = url
        return None

    async def content(self):
        return "<html></html>"

    async def close(self):
        pass


class _FakeContext:
    def __init__(self):
        self.closed = False

    async def new_page(self):
        return _FakePage()

    async def route(self, pattern, handler):
        pass

    async def close(self):
        self.closed = True


class _FakeBrowser:
    async def new_context(self, **kwargs):
        return _FakeContext()


def test_malformed_port_is_rejected():
    with pytest.raises(UrlPolicyError):
        canonicalize_url("https://example.com:not-a-port/")
    with pytest.raises(UrlPolicyError):
        canonicalize_url("https://example.com:99999/")
    assert canonicalize_url("https://example.com:8443/") == "https://example.com:8443/"


def test_request_timeout_is_positive_and_bounded():
    with pytest.raises(ValueError):
        _config(request_timeout=0)
    with pytest.raises(ValueError):
        _config(request_timeout=-1)
    assert _config(request_timeout=7).request_timeout == 7


def test_browser_context_proxy_identity_is_visible():
    manager = BrowserManager(_config(use_playwright=True, browser=BrowserConfig(proxy_rotation="per_context")))
    manager._context_proxy = "http://proxy-a:8080"
    assert manager.current_proxy == "http://proxy-a:8080"
    assert manager.context_rotation_due is False
    manager.request_count = manager.MAX_REQUESTS_PER_CONTEXT
    assert manager.context_rotation_due is True


async def test_resume_filter_is_kind_specific(tmp_path):
    manager = CheckpointManager("kind", True, tmp_path / "checkpoint.sqlite")
    await manager.initialize()
    url = "https://example.com/shared"
    await manager.mark_done(url, kind="nested")
    await manager.mark_failed(url, kind="root")
    incomplete = await manager.get_incomplete(kind="root")
    assert incomplete == [url]
    assert manager.is_done(url, kind="root") is False
    await manager.close()


async def test_browser_proxy_lease_matches_context_until_rotation():
    config = _config(
        use_playwright=True,
        proxies=["http://proxy-a:8080", "http://proxy-b:8080"],
        browser=BrowserConfig(proxy_rotation="per_context", context_max_requests=2),
    )
    engine = ScraperEngine(config)
    assert engine.browser_manager is not None
    engine.browser_manager._context_proxy = "http://proxy-a:8080"
    engine.proxy_pool = cycle(["http://proxy-b:8080"])

    proxy, lease = await engine._get_healthy_proxy()
    assert proxy == "http://proxy-a:8080"
    assert lease is not None
    await lease.succeed()
    engine.browser_manager.request_count = engine.browser_manager.MAX_REQUESTS_PER_CONTEXT
    proxy, lease = await engine._get_healthy_proxy()
    assert proxy == "http://proxy-b:8080"
    assert lease is not None
    await lease.succeed()


async def test_open_browser_proxy_requests_safe_rotation():
    config = _config(
        use_playwright=True,
        proxies=["http://proxy-a:8080", "http://proxy-b:8080"],
        browser=BrowserConfig(proxy_rotation="per_context", context_max_requests=10),
        proxy_failure_threshold=1,
    )
    engine = ScraperEngine(config)
    assert engine.browser_manager is not None
    engine.browser_manager._context_proxy = "http://proxy-a:8080"
    failed = await engine.proxy_health.try_acquire("http://proxy-a:8080")
    assert failed is not None
    await failed.fail()

    proxy, lease = await engine._get_healthy_proxy()

    assert proxy == "http://proxy-b:8080"
    assert lease is not None
    assert engine.browser_manager.context_rotation_due is True
    await lease.succeed()


async def test_requested_rotation_replaces_context_with_selected_proxy():
    manager = BrowserManager(_config(use_playwright=True))
    manager.browser = _FakeBrowser()
    old_context = _FakeContext()
    manager.context = old_context
    manager._context_proxy = "http://proxy-a:8080"
    manager.request_context_rotation()

    await manager.fetch_page("https://example.com/", proxy="http://proxy-b:8080")

    assert old_context.closed is True
    assert manager.current_proxy == "http://proxy-b:8080"
    assert manager.request_count == 1


async def test_robots_deny_policy_and_origin_bound():
    async def failed_fetch(url, purpose, parent_url):
        return type("Result", (), {"error": FetchError(ErrorCategory.NETWORK, url), "status_code": 0, "content": ""})()

    cache = RobotsCache(failed_fetch, failure_policy="deny", max_origins=2)
    assert await cache.can_fetch("https://one.example/page") is False
    assert await cache.can_fetch("https://two.example/page") is False
    assert await cache.can_fetch("https://three.example/page") is False
    assert len(cache._entries) <= 2
    assert len(cache._locks) <= 2


async def test_required_interaction_failure_is_classified():
    config = _config(
        use_playwright=True,
        interaction_failure_policy="fail",
        interactions=[{"type": InteractionType.CLICK, "selector": "#missing"}],
    )
    manager = BrowserManager(config)

    async def fail_action(page, action):
        raise RuntimeError("not found")

    manager._execute_interaction = fail_action  # type: ignore[method-assign]
    page = type("Page", (), {"url": "https://example.com"})()
    with pytest.raises(FetchError) as caught:
        await manager._handle_interactions(page)
    assert caught.value.category == ErrorCategory.INTERACTION


def test_policy_defaults_preserve_compatibility():
    config = _config()
    assert config.interaction_failure_policy == "warn"
    assert config.fail_parent_on_nested_error is True
    assert config.robots_failure_policy == "allow"
