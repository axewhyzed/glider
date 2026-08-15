"""Structured per-domain metrics, latency histogram, and snapshots (P9.1-P9.3)."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class RequestSample:
    origin: str            # canonical origin (engine.network.origin)
    purpose: str           # RequestPurpose.value
    status_code: int
    elapsed_ms: float
    attempts: int
    category: str          # "success" | "http_error" | "parse_error" | "network_error" | "blocked" | ...
    url: str = ""


class Histogram:
    """Fixed log-linear buckets (doubling from 1 ms) with an overflow counter.

    Bounded memory: only bucket counts are stored, so p50/p95 are exact within
    bucket resolution and no sample reservoir is retained.
    """

    def __init__(self) -> None:
        self.buckets: Counter = Counter()
        self.overflow = 0
        self._count = 0
        self._max: Optional[float] = None

    def record(self, ms: float) -> None:
        self._count += 1
        self._max = ms if self._max is None else max(self._max, ms)
        bucket = 0 if ms < 1 else int(math.ceil(math.log2(ms)))
        if bucket > 16:  # > ~18h
            self.overflow += 1
        else:
            self.buckets[bucket] += 1

    @property
    def count(self) -> int:
        return self._count

    def max(self) -> Optional[float]:
        return self._max

    def percentile(self, p: float) -> Optional[float]:
        if self._count == 0:
            return None
        target = self._count * p
        if target <= 0:
            return 0.0
        seen = 0
        prev_bound = 0.0
        for bucket in sorted(self.buckets):
            upper = 2.0 ** bucket
            prev_seen = seen
            seen += self.buckets[bucket]
            if seen >= target:
                if self.buckets[bucket] == 0 or upper <= 1.0:
                    return upper
                # Linear interpolation within the bucket.
                lower = upper / 2.0
                frac = (target - prev_seen) / self.buckets[bucket]
                return lower + frac * (upper - lower)
            prev_bound = upper
        return self._max  # overflow -> report max

    def snapshot(self) -> Dict[str, Optional[float]]:
        return {
            "p50": self.percentile(0.50),
            "p95": self.percentile(0.95),
            "max": self.max(),
            "samples": self._count,
        }


@dataclass
class DomainCounters:
    requests: int = 0
    success: int = 0
    failed: int = 0
    blocked: int = 0
    by_category: Counter = field(default_factory=Counter)
    latency: Histogram = field(default_factory=Histogram)


class MetricsCollector:
    """Collects per-domain request samples and duplicates.

    Single event-loop use: plain dicts are safe under asyncio concurrency.
    """

    def __init__(self) -> None:
        self.domains: Dict[str, DomainCounters] = defaultdict(DomainCounters)
        self.duplicates_detected = 0
        self.latency = Histogram()
        self.events: Counter = Counter()

    def record_event(self, name: str, count: int = 1) -> None:
        self.events[name] += count

    def record(self, sample: RequestSample) -> None:
        dc = self.domains[sample.origin]
        dc.requests += 1
        dc.latency.record(sample.elapsed_ms)
        self.latency.record(sample.elapsed_ms)
        if sample.category == "success":
            dc.success += 1
        elif sample.category == "blocked":
            dc.blocked += 1
        else:
            dc.failed += 1
        dc.by_category[sample.category] += 1

    def record_duplicate(self) -> None:
        self.duplicates_detected += 1

    def snapshot(self) -> Dict[str, Any]:
        domains = {}
        for origin, dc in sorted(self.domains.items()):
            domains[origin] = {
                "requests": dc.requests,
                "success": dc.success,
                "failed": dc.failed,
                "blocked": dc.blocked,
                "by_category": dict(dc.by_category),
                "latency_ms": dc.latency.snapshot(),
            }
        return {
            "domains": domains,
            "duplicates_detected": self.duplicates_detected,
            "events": dict(self.events),
            "latency_ms": self.latency.snapshot(),
        }
