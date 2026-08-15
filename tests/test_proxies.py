import pytest

from engine.proxies import (
    ProxyCircuitBreaker,
    ProxyCircuitBreakerCapacityError,
    ProxyHealthPolicy,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


async def test_open_circuit_allows_only_one_half_open_probe():
    clock = FakeClock()
    breaker = ProxyCircuitBreaker(
        ProxyHealthPolicy(failure_threshold=2, cooldown_seconds=10), clock=clock
    )

    first = await breaker.try_acquire("http://proxy-a")
    assert first is not None
    await first.fail()
    second = await breaker.try_acquire("http://proxy-a")
    assert second is not None
    await second.fail()

    assert await breaker.try_acquire("http://proxy-a") is None
    clock.now = 10
    probe = await breaker.try_acquire("http://proxy-a")
    assert probe is not None
    assert await breaker.try_acquire("http://proxy-a") is None
    await probe.succeed()

    recovered = await breaker.try_acquire("http://proxy-a")
    assert recovered is not None
    await recovered.succeed()
    state = await breaker.snapshot()
    assert state["http://proxy-a"]["state"] == "closed"
    assert state["http://proxy-a"]["consecutive_failures"] == 0


async def test_stale_success_cannot_close_newly_opened_circuit():
    breaker = ProxyCircuitBreaker(ProxyHealthPolicy(failure_threshold=1, cooldown_seconds=30))
    old = await breaker.try_acquire("http://proxy-a")
    opener = await breaker.try_acquire("http://proxy-a")
    assert old is not None and opener is not None

    await opener.fail()
    await old.succeed()
    state = await breaker.snapshot()
    assert state["http://proxy-a"]["state"] == "open"


async def test_state_capacity_evicts_idle_but_not_active_entries():
    breaker = ProxyCircuitBreaker(ProxyHealthPolicy(max_proxies=1))
    idle = await breaker.try_acquire("http://proxy-a")
    assert idle is not None
    await idle.succeed()
    replacement = await breaker.try_acquire("http://proxy-b")
    assert replacement is not None
    await replacement.succeed()
    assert set(await breaker.snapshot()) == {"http://proxy-b"}

    active = await breaker.try_acquire("http://proxy-b")
    assert active is not None
    with pytest.raises(ProxyCircuitBreakerCapacityError):
        await breaker.try_acquire("http://proxy-c")
    await active.fail()


async def test_lease_context_manager_records_failure_and_success():
    breaker = ProxyCircuitBreaker(ProxyHealthPolicy(failure_threshold=1))
    lease = await breaker.try_acquire("http://proxy-a")
    assert lease is not None
    with pytest.raises(RuntimeError):
        async with lease:
            raise RuntimeError("request failed")
    assert await breaker.try_acquire("http://proxy-a") is None
