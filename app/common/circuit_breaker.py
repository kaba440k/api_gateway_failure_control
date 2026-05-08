from dataclasses import dataclass
from enum import StrEnum
from time import time

from redis.asyncio import Redis


class BreakerState(StrEnum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


@dataclass(frozen=True)
class BreakerSnapshot:
    service: str
    state: BreakerState
    failures: int
    opened_until: float

    @property
    def seconds_until_probe(self) -> float:
        return max(0.0, self.opened_until - time())


class CircuitBreaker:
    def __init__(
        self,
        redis: Redis,
        service: str,
        failure_threshold: int,
        open_timeout_seconds: int,
    ) -> None:
        self.redis = redis
        self.service = service
        self.failure_threshold = failure_threshold
        self.open_timeout_seconds = open_timeout_seconds
        self.key = f"circuit:{service}"

    async def snapshot(self) -> BreakerSnapshot:
        raw = await self.redis.hgetall(self.key)
        state = BreakerState(raw.get("state", BreakerState.CLOSED))
        failures = int(raw.get("failures", 0))
        opened_until = float(raw.get("opened_until", 0.0))

        if state == BreakerState.OPEN and opened_until <= time():
            state = BreakerState.HALF_OPEN
            await self.redis.hset(self.key, mapping={"state": state, "failures": failures})

        return BreakerSnapshot(
            service=self.service,
            state=state,
            failures=failures,
            opened_until=opened_until,
        )

    async def allow_request(self) -> BreakerSnapshot:
        snapshot = await self.snapshot()
        if snapshot.state == BreakerState.OPEN:
            return snapshot
        return snapshot

    async def record_success(self) -> BreakerSnapshot:
        await self.redis.hset(
            self.key,
            mapping={
                "state": BreakerState.CLOSED,
                "failures": 0,
                "opened_until": 0.0,
            },
        )
        return await self.snapshot()

    async def record_failure(self) -> BreakerSnapshot:
        snapshot = await self.snapshot()
        failures = snapshot.failures + 1
        state = snapshot.state
        opened_until = snapshot.opened_until

        if snapshot.state == BreakerState.HALF_OPEN or failures >= self.failure_threshold:
            state = BreakerState.OPEN
            opened_until = time() + self.open_timeout_seconds

        await self.redis.hset(
            self.key,
            mapping={
                "state": state,
                "failures": failures,
                "opened_until": opened_until,
            },
        )
        return await self.snapshot()

    async def reset(self) -> BreakerSnapshot:
        await self.redis.delete(self.key)
        return await self.snapshot()
