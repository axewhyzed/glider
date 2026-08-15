"""Async-safe, bounded proxy health tracking with circuit breaking."""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Dict, Optional


class ProxyCircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class ProxyCircuitBreakerCapacityError(RuntimeError):
    """Raised when state is full and every retained proxy has active work."""


@dataclass(frozen=True)
class ProxyHealthPolicy:
    """Circuit-breaker configuration for a shared proxy pool."""

    failure_threshold: int = 3
    cooldown_seconds: float = 30.0
    max_proxies: int = 1_000
    idle_ttl_seconds: float = 3_600.0

    def __post_init__(self) -> None:
        if self.failure_threshold < 1:
            raise ValueError("failure_threshold must be at least one")
        if self.cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be non-negative")
        if self.max_proxies < 1:
            raise ValueError("max_proxies must be at least one")
        if self.idle_ttl_seconds < 0:
            raise ValueError("idle_ttl_seconds must be non-negative")


@dataclass
class _ProxyRecord:
    state: ProxyCircuitState
    consecutive_failures: int
    opened_until: float
    last_used_at: float
    active_leases: int = 0
    probe_active: bool = False
    generation: int = 0


class ProxyLease:
    """One proxy attempt whose outcome closes the circuit-breaker feedback loop."""

    def __init__(self, breaker: "ProxyCircuitBreaker", proxy: str, generation: int) -> None:
        self.proxy = proxy
        self._breaker = breaker
        self._generation = generation
        self._resolved = False

    async def succeed(self) -> None:
        """Record a successful proxy attempt.  Safe to call more than once."""

        if not self._resolved:
            self._resolved = True
            await self._breaker._resolve(self.proxy, self._generation, success=True)

    async def fail(self) -> None:
        """Record a failed proxy attempt.  Safe to call more than once."""

        if not self._resolved:
            self._resolved = True
            await self._breaker._resolve(self.proxy, self._generation, success=False)

    async def abandon(self) -> None:
        """Release a reservation that was never used, without an outcome."""

        if not self._resolved:
            self._resolved = True
            await self._breaker._release(self.proxy, self._generation)

    async def __aenter__(self) -> "ProxyLease":
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> bool:
        if exc_type is None:
            await self.succeed()
        else:
            await self.fail()
        return False


class ProxyCircuitBreaker:
    """Track proxy outcomes and prevent use of unhealthy proxies.

    ``try_acquire`` returns ``None`` for an open circuit.  After cooldown, one
    half-open probe is admitted; concurrent callers continue to receive None
    until that lease reports success or failure.
    """

    def __init__(
        self,
        policy: ProxyHealthPolicy = ProxyHealthPolicy(),
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.policy = policy
        self._clock = clock
        self._lock = asyncio.Lock()
        self._records: "OrderedDict[str, _ProxyRecord]" = OrderedDict()

    async def try_acquire(self, proxy: str) -> Optional[ProxyLease]:
        """Reserve a proxy attempt, or return ``None`` if its circuit is open."""

        if not proxy or not proxy.strip():
            raise ValueError("proxy must be a non-empty string")
        key = proxy.strip()
        async with self._lock:
            now = self._clock()
            self._prune_idle(now)
            record = self._get_or_create_record(key, now)
            if record.state is ProxyCircuitState.OPEN:
                if now < record.opened_until:
                    record.last_used_at = now
                    self._records.move_to_end(key)
                    return None
                record.state = ProxyCircuitState.HALF_OPEN
                record.probe_active = False

            if record.state is ProxyCircuitState.HALF_OPEN and record.probe_active:
                return None

            record.active_leases += 1
            record.last_used_at = now
            if record.state is ProxyCircuitState.HALF_OPEN:
                record.probe_active = True
            self._records.move_to_end(key)
            return ProxyLease(self, key, record.generation)

    async def snapshot(self) -> Dict[str, Dict[str, int | float | str | bool]]:
        """Return a copy of health state for observability and tests."""

        async with self._lock:
            now = self._clock()
            self._prune_idle(now)
            return {
                proxy: {
                    "state": record.state.value,
                    "consecutive_failures": record.consecutive_failures,
                    "opened_until": record.opened_until,
                    "active_leases": record.active_leases,
                    "probe_active": record.probe_active,
                }
                for proxy, record in self._records.items()
            }

    async def _resolve(self, proxy: str, generation: int, *, success: bool) -> None:
        async with self._lock:
            record = self._records.get(proxy)
            if record is None:
                return
            record.active_leases = max(0, record.active_leases - 1)
            record.last_used_at = self._clock()

            # An outcome from a request begun before the circuit opened must not
            # close or otherwise mutate the newer circuit state.
            if generation != record.generation:
                return

            record.probe_active = False
            if success:
                record.state = ProxyCircuitState.CLOSED
                record.consecutive_failures = 0
                record.opened_until = 0.0
                return

            record.consecutive_failures += 1
            if record.state is ProxyCircuitState.HALF_OPEN or (
                record.consecutive_failures >= self.policy.failure_threshold
            ):
                self._open(record, record.last_used_at)

    async def _release(self, proxy: str, generation: int) -> None:
        """Release an unused lease without changing circuit state."""

        async with self._lock:
            record = self._records.get(proxy)
            if record is None:
                return
            record.active_leases = max(0, record.active_leases - 1)
            record.last_used_at = self._clock()

    def _get_or_create_record(self, proxy: str, now: float) -> _ProxyRecord:
        record = self._records.get(proxy)
        if record is not None:
            return record
        if len(self._records) >= self.policy.max_proxies:
            evictable = next(
                (
                    key
                    for key, value in self._records.items()
                    if value.active_leases == 0 and not value.probe_active
                ),
                None,
            )
            if evictable is None:
                raise ProxyCircuitBreakerCapacityError(
                    "all proxy health entries have active leases; cannot add another proxy"
                )
            del self._records[evictable]
        record = _ProxyRecord(
            state=ProxyCircuitState.CLOSED,
            consecutive_failures=0,
            opened_until=0.0,
            last_used_at=now,
        )
        self._records[proxy] = record
        return record

    def _open(self, record: _ProxyRecord, now: float) -> None:
        record.state = ProxyCircuitState.OPEN
        record.opened_until = now + self.policy.cooldown_seconds
        record.probe_active = False
        record.generation += 1

    def _prune_idle(self, now: float) -> None:
        if self.policy.idle_ttl_seconds == 0:
            return
        stale = [
            proxy
            for proxy, record in self._records.items()
            if (
                record.state is ProxyCircuitState.CLOSED
                and record.active_leases == 0
                and now - record.last_used_at >= self.policy.idle_ttl_seconds
            )
        ]
        for proxy in stale:
            del self._records[proxy]
