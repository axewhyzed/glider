"""Per-origin robots.txt cache fetched through the engine's own fetch path.

Every origin's robots.txt is fetched through ``_fetch_page`` (purpose=ROBOTS),
so it inherits URL policy validation, proxies, rate limiting, and retries.
A missing, unparseable, or network-failing robots.txt follows the configured
failure policy: ``allow`` preserves availability-oriented allow-all behavior,
while ``deny`` blocks the affected origin. Failures are logged.
"""

from __future__ import annotations

import asyncio
import time
import urllib.robotparser
from dataclasses import dataclass
from collections import OrderedDict
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
        failure_policy: str = "allow",
        max_origins: int = 1000,
    ) -> None:
        self._fetcher = fetcher
        self.user_agent = user_agent
        self.ttl_seconds = ttl_seconds
        if failure_policy not in {"allow", "deny"}:
            raise ValueError("failure_policy must be 'allow' or 'deny'")
        if max_origins < 1:
            raise ValueError("max_origins must be at least one")
        self.failure_policy = failure_policy
        self.max_origins = max_origins
        self._entries: "OrderedDict[str, _RobotsEntry]" = OrderedDict()
        self._locks: "OrderedDict[str, asyncio.Lock]" = OrderedDict()

    def _entry_for(self, host: str) -> Optional[_RobotsEntry]:
        entry = self._entries.get(host)
        if entry is None:
            return None
        # ttl_seconds == 0 means "always stale" (refetch every call).
        if self.ttl_seconds == 0 or (time.monotonic() - entry.fetched_at) > self.ttl_seconds:
            self._entries.pop(host, None)
            return None
        self._entries.move_to_end(host)
        return entry

    def _trim_state(self) -> None:
        while len(self._entries) > self.max_origins:
            self._entries.popitem(last=False)
        for host in list(self._locks):
            lock = self._locks[host]
            if host not in self._entries and not lock.locked():
                del self._locks[host]

    async def can_fetch(self, url: str, parent_url: Optional[str] = None) -> bool:
        """Origin-cached robots check honoring the configured failure policy."""
        from engine.network import origin

        host = origin(url)
        entry = self._entry_for(host)
        if entry is not None:
            return self._allows(entry, url)

        lock = self._locks.get(host)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[host] = lock
        self._locks.move_to_end(host)
        async with lock:
            entry = self._entry_for(host)
            if entry is not None:
                return self._allows(entry, url)
            entry = await self._fetch_robots(host, url)
            self._entries[host] = entry
            self._entries.move_to_end(host)
            self._trim_state()
        return self._allows(entry, url)

    def _allows(self, entry: _RobotsEntry, url: str) -> bool:
        if entry.parser is None:
            return self.failure_policy == "allow"
        return entry.parser.can_fetch(self.user_agent, url)

    async def _fetch_robots(self, host: str, sample_url: str) -> _RobotsEntry:
        """Fetch {scheme}://{netloc}/robots.txt through the engine fetcher."""
        robots_url = f"{host}/robots.txt"
        try:
            result = await self._fetcher(robots_url, RequestPurpose.ROBOTS, None)
        except Exception as exc:
            logger.warning(f"Robots fetch failed for {host}: {exc}. Applying {self.failure_policy} policy.")
            return _RobotsEntry(None, time.monotonic())
        if result.error is not None:
            logger.warning(f"Robots fetch error for {host}: {result.error}. Applying {self.failure_policy} policy.")
            return _RobotsEntry(None, time.monotonic())
        if not (200 <= result.status_code < 300):
            logger.info(f"Robots {result.status_code} for {host}. Applying {self.failure_policy} policy.")
            return _RobotsEntry(None, time.monotonic())

        parser = urllib.robotparser.RobotFileParser()
        try:
            parser.parse(result.content.splitlines())
        except Exception as exc:
            logger.warning(f"Robots parse failed for {host}: {exc}. Applying {self.failure_policy} policy.")
            return _RobotsEntry(None, time.monotonic())
        return _RobotsEntry(parser, time.monotonic())
