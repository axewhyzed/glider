"""Per-origin robots.txt cache fetched through the engine's own fetch path.

Every origin's robots.txt is fetched through ``_fetch_page`` (purpose=ROBOTS),
so it inherits URL policy validation, proxies, rate limiting, and retries.
A missing, unparseable, or network-failing robots.txt is treated as allow-all
(permissive) and logged — a transient robots failure must not block a crawl.
"""

from __future__ import annotations

import asyncio
import time
import urllib.robotparser
from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, Optional

from loguru import logger

from engine.network import FetchResult, RequestPurpose


@dataclass
class _RobotsEntry:
    parser: Optional[urllib.robotparser.RobotFileParser]
    fetched_at: float


class RobotsCache:
    """Origin-keyed, TTL-bounded robots.txt cache."""

    def __init__(
        self,
        fetcher: Callable[[str, RequestPurpose, Optional[str]], Awaitable[FetchResult]],
        user_agent: str = "*",
        ttl_seconds: float = 3600.0,
    ) -> None:
        self._fetcher = fetcher
        self.user_agent = user_agent
        self.ttl_seconds = ttl_seconds
        self._entries: Dict[str, _RobotsEntry] = {}
        self._locks: Dict[str, asyncio.Lock] = {}

    def _entry_for(self, host: str) -> Optional[_RobotsEntry]:
        entry = self._entries.get(host)
        if entry is None:
            return None
        # ttl_seconds == 0 means "always stale" (refetch every call).
        if self.ttl_seconds == 0 or (time.monotonic() - entry.fetched_at) > self.ttl_seconds:
            self._entries.pop(host, None)
            return None
        return entry

    async def can_fetch(self, url: str, parent_url: Optional[str] = None) -> bool:
        """Origin-cached robots check. Returns True (allow) on any fetch/parse failure."""
        from engine.network import origin

        host = origin(url)
        entry = self._entry_for(host)
        if entry is not None:
            return self._allows(entry, url)

        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            entry = self._entry_for(host)
            if entry is not None:
                return self._allows(entry, url)
            entry = await self._fetch_robots(host, url)
            self._entries[host] = entry
        return self._allows(entry, url)

    def _allows(self, entry: _RobotsEntry, url: str) -> bool:
        if entry.parser is None:
            return True  # missing/unparseable robots -> allow-all
        return entry.parser.can_fetch(self.user_agent, url)

    async def _fetch_robots(self, host: str, sample_url: str) -> _RobotsEntry:
        """Fetch {scheme}://{netloc}/robots.txt through the engine fetcher."""
        robots_url = f"{host}/robots.txt"
        try:
            result = await self._fetcher(robots_url, RequestPurpose.ROBOTS, None)
        except Exception as exc:
            logger.warning(f"Robots fetch failed for {host}: {exc}. Allowing.")
            return _RobotsEntry(None, time.monotonic())
        if result.error is not None:
            logger.warning(f"Robots fetch error for {host}: {result.error}. Allowing.")
            return _RobotsEntry(None, time.monotonic())
        if not (200 <= result.status_code < 300):
            logger.info(f"Robots {result.status_code} for {host}. Allowing.")
            return _RobotsEntry(None, time.monotonic())

        parser = urllib.robotparser.RobotFileParser()
        try:
            parser.parse(result.content.splitlines())
        except Exception as exc:
            logger.warning(f"Robots parse failed for {host}: {exc}. Allowing.")
            return _RobotsEntry(None, time.monotonic())
        return _RobotsEntry(parser, time.monotonic())
