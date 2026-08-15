"""Tests for engine.robots: per-origin robots.txt cache (P3.1)."""

import asyncio

import pytest

from engine.network import FetchResult, RequestPurpose
from engine.robots import RobotsCache

DISALLOW_ALL = "User-agent: *\nDisallow: /\n"
ALLOW_ALL = "User-agent: *\nDisallow:\n"
PARTIAL = "User-agent: *\nDisallow: /private/\n"


class FakeFetcher:
    """Records calls and returns canned robots responses by origin."""

    def __init__(self, responses=None, raise_error=None):
        self.responses = responses or {}
        self.raise_error = raise_error
        self.calls = []

    async def __call__(self, url, purpose, parent_url=None):
        self.calls.append((url, purpose, parent_url))
        if self.raise_error:
            raise self.raise_error
        status = 200
        content = self.responses.get(url, ALLOW_ALL)
        if content is None:
            status = 404
            content = ""
        return FetchResult(content=content, requested_url=url, final_url=url, status_code=status)


@pytest.fixture
def robots():
    return RobotsCache(FakeFetcher(), ttl_seconds=3600.0)


async def test_single_origin_fetched_once(robots):
    assert await robots.can_fetch("https://example.com/a") is True
    assert await robots.can_fetch("https://example.com/b") is True
    # One origin -> one robots fetch total.
    assert len(robots._fetcher.calls) == 1


async def test_per_origin_isolated():
    fetcher = FakeFetcher({
        "https://blocked.com/robots.txt": DISALLOW_ALL,
        "https://open.com/robots.txt": ALLOW_ALL,
    })
    cache = RobotsCache(fetcher)
    assert await cache.can_fetch("https://blocked.com/x") is False
    assert await cache.can_fetch("https://open.com/x") is True


async def test_robots_disallow_blocks():
    fetcher = FakeFetcher({"https://site.com/robots.txt": PARTIAL})
    cache = RobotsCache(fetcher)
    assert await cache.can_fetch("https://site.com/private/x") is False
    assert await cache.can_fetch("https://site.com/public") is True


async def test_robots_404_allows():
    fetcher = FakeFetcher({"https://missing.com/robots.txt": None})
    cache = RobotsCache(fetcher)
    assert await cache.can_fetch("https://missing.com/x") is True


async def test_robots_network_failure_allows():
    cache = RobotsCache(FakeFetcher(raise_error=OSError("connection refused")))
    assert await cache.can_fetch("https://down.com/x") is True


async def test_robots_unparseable_allows():
    fetcher = FakeFetcher({"https://garbage.com/robots.txt": "@@@ not robots @@@"})
    cache = RobotsCache(fetcher)
    assert await cache.can_fetch("https://garbage.com/x") is True


async def test_robots_ttl_refetches():
    fetcher = FakeFetcher({"https://site.com/robots.txt": ALLOW_ALL})
    cache = RobotsCache(fetcher, ttl_seconds=0.0)  # always stale
    await cache.can_fetch("https://site.com/a")
    await cache.can_fetch("https://site.com/b")
    assert len(fetcher.calls) == 2


async def test_concurrent_first_fetch_single_request():
    fetcher = FakeFetcher({"https://site.com/robots.txt": ALLOW_ALL})
    cache = RobotsCache(fetcher)
    results = await asyncio.gather(
        *(cache.can_fetch("https://site.com/x") for _ in range(10))
    )
    assert all(results)
    assert len(fetcher.calls) == 1


async def test_robots_fetch_uses_robots_purpose():
    fetcher = FakeFetcher()
    cache = RobotsCache(fetcher)
    await cache.can_fetch("https://example.com/x")
    url, purpose, parent = fetcher.calls[0]
    assert url == "https://example.com/robots.txt"
    assert purpose == RequestPurpose.ROBOTS
    assert parent is None
