import pytest

import app.common.circuit_breaker as circuit_module
from app.common.circuit_breaker import BreakerState, CircuitBreaker


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, dict[str, object]] = {}

    async def hgetall(self, key: str) -> dict[str, object]:
        return dict(self.data.get(key, {}))

    async def hset(self, key: str, mapping: dict[str, object]) -> None:
        self.data.setdefault(key, {}).update(mapping)

    async def delete(self, key: str) -> None:
        self.data.pop(key, None)


@pytest.fixture
def redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def breaker(redis: FakeRedis) -> CircuitBreaker:
    return CircuitBreaker(
        redis=redis,
        service="unstable-service",
        failure_threshold=3,
        open_timeout_seconds=10,
    )


@pytest.mark.asyncio
async def test_initial_state_is_closed(breaker: CircuitBreaker) -> None:
    snapshot = await breaker.snapshot()

    assert snapshot.state == BreakerState.CLOSED
    assert snapshot.failures == 0


@pytest.mark.asyncio
async def test_breaker_opens_after_failure_threshold(breaker: CircuitBreaker) -> None:
    await breaker.record_failure()
    await breaker.record_failure()
    snapshot = await breaker.record_failure()

    assert snapshot.state == BreakerState.OPEN
    assert snapshot.failures == 3
    assert snapshot.opened_until > 0


@pytest.mark.asyncio
async def test_open_breaker_moves_to_half_open_after_timeout(
    breaker: CircuitBreaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_time = 1000.0
    monkeypatch.setattr(circuit_module, "time", lambda: current_time)
    opened = await breaker.record_failure()
    await breaker.record_failure()
    opened = await breaker.record_failure()

    assert opened.state == BreakerState.OPEN

    current_time = 1011.0
    snapshot = await breaker.snapshot()

    assert snapshot.state == BreakerState.HALF_OPEN


@pytest.mark.asyncio
async def test_success_closes_breaker_and_resets_failures(breaker: CircuitBreaker) -> None:
    await breaker.record_failure()
    await breaker.record_failure()

    snapshot = await breaker.record_success()

    assert snapshot.state == BreakerState.CLOSED
    assert snapshot.failures == 0


@pytest.mark.asyncio
async def test_reset_removes_breaker_state(breaker: CircuitBreaker) -> None:
    await breaker.record_failure()
    await breaker.record_failure()
    await breaker.record_failure()

    snapshot = await breaker.reset()

    assert snapshot.state == BreakerState.CLOSED
    assert snapshot.failures == 0
