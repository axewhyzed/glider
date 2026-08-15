"""Async, bounded per-domain token-bucket rate limiting.

This module intentionally has no scraper dependency.  Callers can share one
``DomainRateLimiter`` across HTTP, browser, and child-request code paths.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator, Awaitable, Callable, Dict
from urllib.parse import urlsplit


class RateLimiterCapacityError(RuntimeError):
    """Raised when all bounded limiter entries are actively waiting."""


@dataclass(frozen=True)
class DomainRateLimitPolicy:
    """Configuration for one shared :class:`DomainRateLimiter`.

    ``rate_per_second`` is the sustained rate for each hostname and ``burst``
    is the maximum immediately available permit balance.  ``max_domains`` and
    ``idle_ttl_seconds`` bound retained state for long-running crawls.
    """

    rate_per_second: float
    burst: float = 1.0
    max_domains: int = 1_000
    idle_ttl_seconds: float = 900.0

    def __post_init__(self) -> None:
        if self.rate_per_second <= 0:
            raise ValueError("rate_per_second must be greater than zero")
        if self.burst <= 0:
            raise ValueError("burst must be greater than zero")
        if self.max_domains < 1:
            raise ValueError("max_domains must be at least one")
        if self.idle_ttl_seconds < 0:
            raise ValueError("idle_ttl_seconds must be non-negative")


@dataclass
class _Bucket:
    tokens: float
    refreshed_at: float
    last_used_at: float
    waiters: int = 0


def domain_key(target: str) -> str:
    """Return the normalized hostname used as the limiter key.

    A hostname (rather than an origin) deliberately shares a limit across HTTP
    and HTTPS, as well as across non-default ports of the same host.
    """

    parsed = urlsplit(target)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if not parsed.scheme or not hostname:
        raise ValueError("target must be an absolute URL with a hostname")
    return hostname


class DomainRateLimiter:
    """A cancellation-safe token bucket for each domain.

    The internal lock only protects token accounting; it is never held while a
    caller waits.  Entries with waiting callers cannot be evicted, so bounded
    eviction cannot silently reset an in-flight domain's rate limit.
    """

    def __init__(
        self,
        policy: DomainRateLimitPolicy,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.policy = policy
        self._clock = clock
        self._sleep = sleep
        self._lock = asyncio.Lock()
        self._buckets: "OrderedDict[str, _Bucket]" = OrderedDict()

    async def acquire(self, target: str, permits: float = 1.0) -> None:
        """Wait until ``permits`` can be consumed for ``target``'s domain."""

        if permits <= 0:
            raise ValueError("permits must be greater than zero")
        if permits > self.policy.burst:
            raise ValueError("permits cannot exceed the configured burst")

        key = domain_key(target)
        registered_waiter = False
        try:
            while True:
                async with self._lock:
                    now = self._clock()
                    self._prune_idle(now)
                    bucket = self._get_or_create_bucket(key, now)
                    self._refill(bucket, now)
                    bucket.last_used_at = now
                    self._buckets.move_to_end(key)
                    if bucket.tokens >= permits:
                        bucket.tokens -= permits
                        return

                    if not registered_waiter:
                        bucket.waiters += 1
                        registered_waiter = True
                    delay = (permits - bucket.tokens) / self.policy.rate_per_second
                await self._sleep(delay)
        finally:
            if registered_waiter:
                async with self._lock:
                    bucket = self._buckets.get(key)
                    if bucket is not None:
                        bucket.waiters = max(0, bucket.waiters - 1)

    @asynccontextmanager
    async def limit(self, target: str, permits: float = 1.0) -> AsyncIterator[None]:
        """Acquire a domain permit for the duration of an ``async with`` block."""

        await self.acquire(target, permits)
        yield

    async def snapshot(self) -> Dict[str, Dict[str, float | int]]:
        """Return a copy of current bounded state for diagnostics/tests."""

        async with self._lock:
            now = self._clock()
            self._prune_idle(now)
            for bucket in self._buckets.values():
                self._refill(bucket, now)
            return {
                domain: {
                    "tokens": bucket.tokens,
                    "waiters": bucket.waiters,
                    "last_used_at": bucket.last_used_at,
                }
                for domain, bucket in self._buckets.items()
            }

    def _get_or_create_bucket(self, key: str, now: float) -> _Bucket:
        bucket = self._buckets.get(key)
        if bucket is not None:
            return bucket

        if len(self._buckets) >= self.policy.max_domains:
            evictable = next(
                (domain for domain, item in self._buckets.items() if item.waiters == 0),
                None,
            )
            if evictable is None:
                raise RateLimiterCapacityError(
                    "all domain limiter entries have waiting callers; cannot add another domain"
                )
            del self._buckets[evictable]

        bucket = _Bucket(self.policy.burst, now, now)
        self._buckets[key] = bucket
        return bucket

    def _prune_idle(self, now: float) -> None:
        if self.policy.idle_ttl_seconds == 0:
            return
        stale = [
            domain
            for domain, bucket in self._buckets.items()
            if bucket.waiters == 0 and now - bucket.last_used_at >= self.policy.idle_ttl_seconds
        ]
        for domain in stale:
            del self._buckets[domain]

    def _refill(self, bucket: _Bucket, now: float) -> None:
        elapsed = max(0.0, now - bucket.refreshed_at)
        bucket.tokens = min(
            self.policy.burst,
            bucket.tokens + elapsed * self.policy.rate_per_second,
        )
        bucket.refreshed_at = now
