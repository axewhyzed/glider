import asyncio

import pytest

from engine.limits import (
    DomainRateLimitPolicy,
    DomainRateLimiter,
    RateLimiterCapacityError,
    domain_key,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.delays: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, delay: float) -> None:
        self.delays.append(delay)
        self.now += delay
        await asyncio.sleep(0)


def test_domain_key_normalizes_hostname_and_requires_absolute_url():
    assert domain_key("HTTPS://Example.COM.:8443/path") == "example.com"
    with pytest.raises(ValueError):
        domain_key("example.com/path")


async def test_domains_have_independent_token_buckets():
    clock = FakeClock()
    limiter = DomainRateLimiter(
        DomainRateLimitPolicy(rate_per_second=1, burst=1), clock=clock, sleep=clock.sleep
    )

    await limiter.acquire("https://one.example/a")
    await limiter.acquire("https://two.example/a")
    assert clock.delays == []

    await limiter.acquire("https://one.example/b")
    assert clock.delays == [1.0]


async def test_waiting_domain_is_not_evicted_when_state_is_full():
    clock = FakeClock()
    limiter = DomainRateLimiter(
        DomainRateLimitPolicy(rate_per_second=1, burst=1, max_domains=1),
        clock=clock,
        sleep=clock.sleep,
    )
    await limiter.acquire("https://one.example/")

    waiting = asyncio.create_task(limiter.acquire("https://one.example/again"))
    await asyncio.sleep(0)
    with pytest.raises(RateLimiterCapacityError, match="waiting callers"):
        await limiter.acquire("https://two.example/")
    await waiting


async def test_idle_entries_are_pruned_and_state_is_bounded():
    clock = FakeClock()
    limiter = DomainRateLimiter(
        DomainRateLimitPolicy(rate_per_second=10, burst=1, max_domains=2, idle_ttl_seconds=5),
        clock=clock,
        sleep=clock.sleep,
    )
    await limiter.acquire("https://one.example/")
    clock.now = 6
    await limiter.acquire("https://two.example/")
    state = await limiter.snapshot()
    assert set(state) == {"two.example"}
