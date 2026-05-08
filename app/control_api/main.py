from time import perf_counter
from typing import Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.common.circuit_breaker import BreakerState, CircuitBreaker
from app.common.config import Settings, get_settings
from app.common.database import get_session
from app.common.logging import get_logger, setup_logging
from app.common.metrics import BREAKER_EVENTS, RETRY_EVENTS, setup_metrics
from app.common.models import TrafficEvent
from app.common.redis_client import create_redis, get_redis
from app.control_api.schemas import EventOut, FaultConfig, ProtectedCallOut

logger = get_logger("control-api")


class UpstreamFailure(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


def create_app() -> FastAPI:
    setup_logging()
    settings = get_settings()
    app = FastAPI(title="Failure Control API", version="0.1.0")
    setup_metrics(app, settings.app_name)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    async def startup() -> None:
        redis = create_redis()
        await redis.setnx("fault:unstable-service:enabled", "false")
        await redis.setnx("fault:unstable-service:error_rate", "0")
        await redis.setnx("fault:unstable-service:latency_ms", "0")
        await redis.aclose()
        logger.info("control_api_started")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"service": "control-api", "status": "ok"}

    @app.get("/state")
    async def state(
        redis: Redis = Depends(get_redis),
        settings: Settings = Depends(get_settings),
    ) -> dict[str, Any]:
        breaker = build_breaker(redis, settings)
        snapshot = await breaker.snapshot()
        return {
            "breaker": {
                "service": snapshot.service,
                "state": snapshot.state,
                "failures": snapshot.failures,
                "seconds_until_probe": round(snapshot.seconds_until_probe, 2),
            },
            "fault": await read_fault(redis),
            "links": {
                "gateway": settings.gateway_url,
                "prometheus": settings.prometheus_url,
                "grafana": settings.grafana_url,
            },
        }

    @app.post("/faults/unstable-service")
    async def configure_fault(
        config: FaultConfig,
        redis: Redis = Depends(get_redis),
        session: AsyncSession = Depends(get_session),
    ) -> dict[str, Any]:
        await redis.set("fault:unstable-service:enabled", str(config.enabled).lower())
        await redis.set("fault:unstable-service:error_rate", str(config.error_rate))
        await redis.set("fault:unstable-service:latency_ms", str(config.latency_ms))
        await log_event(
            session,
            service="unstable-service",
            event_type="fault_configured",
            details=config.model_dump(),
        )
        return {"fault": await read_fault(redis)}

    @app.post("/circuit/reset")
    async def reset_circuit(
        redis: Redis = Depends(get_redis),
        session: AsyncSession = Depends(get_session),
        settings: Settings = Depends(get_settings),
    ) -> dict[str, Any]:
        snapshot = await build_breaker(redis, settings).reset()
        BREAKER_EVENTS.labels("unstable-service", "reset", snapshot.state).inc()
        await log_event(
            session,
            service="unstable-service",
            event_type="circuit_reset",
            breaker_state=snapshot.state,
        )
        return {"breaker": snapshot.__dict__}

    @app.get("/proxy/unstable", response_model=ProtectedCallOut)
    async def protected_unstable_call(
        redis: Redis = Depends(get_redis),
        session: AsyncSession = Depends(get_session),
        settings: Settings = Depends(get_settings),
    ) -> ProtectedCallOut:
        breaker = build_breaker(redis, settings)
        snapshot = await breaker.allow_request()
        if snapshot.state == BreakerState.OPEN:
            BREAKER_EVENTS.labels("unstable-service", "rejected", snapshot.state).inc()
            await log_event(
                session,
                service="unstable-service",
                event_type="circuit_rejected",
                status_code=503,
                breaker_state=snapshot.state,
                details={"seconds_until_probe": snapshot.seconds_until_probe},
            )
            return ProtectedCallOut(
                ok=False,
                breaker_state=snapshot.state,
                status_code=503,
                attempts=0,
                error="Circuit breaker is OPEN",
            )

        attempts = 0
        start = perf_counter()
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(settings.retry_attempts),
                wait=wait_exponential(
                    multiplier=settings.retry_initial_delay_seconds,
                    max=settings.retry_max_delay_seconds,
                ),
                retry=retry_if_exception_type((httpx.HTTPError, UpstreamFailure)),
                reraise=True,
            ):
                with attempt:
                    attempts += 1
                    payload = await call_unstable(settings.upstream_unstable_url)
                    updated = await breaker.record_success()
                    RETRY_EVENTS.labels("unstable-service", "success").inc()
                    await log_event(
                        session,
                        service="unstable-service",
                        event_type="request_success",
                        status_code=200,
                        latency_ms=elapsed_ms(start),
                        breaker_state=updated.state,
                        details={"attempts": attempts, "payload": payload},
                    )
                    return ProtectedCallOut(
                        ok=True,
                        breaker_state=updated.state,
                        status_code=200,
                        attempts=attempts,
                        payload=payload,
                    )
        except Exception as exc:
            updated = await breaker.record_failure()
            RETRY_EVENTS.labels("unstable-service", "failed").inc()
            BREAKER_EVENTS.labels("unstable-service", "failure", updated.state).inc()
            status_code = getattr(exc, "status_code", 503)
            await log_event(
                session,
                service="unstable-service",
                event_type="request_failed",
                status_code=status_code,
                latency_ms=elapsed_ms(start),
                breaker_state=updated.state,
                details={"attempts": attempts, "error": str(exc)},
            )
            return ProtectedCallOut(
                ok=False,
                breaker_state=updated.state,
                status_code=status_code,
                attempts=attempts,
                error=str(exc),
            )

        raise HTTPException(status_code=500, detail="Unexpected protected call state")

    @app.get("/events", response_model=list[EventOut])
    async def events(
        limit: int = Query(default=30, ge=1, le=200),
        session: AsyncSession = Depends(get_session),
    ) -> list[TrafficEvent]:
        result = await session.execute(
            select(TrafficEvent).order_by(desc(TrafficEvent.created_at)).limit(limit)
        )
        return list(result.scalars().all())

    return app


def build_breaker(redis: Redis, settings: Settings) -> CircuitBreaker:
    return CircuitBreaker(
        redis=redis,
        service="unstable-service",
        failure_threshold=settings.circuit_failure_threshold,
        open_timeout_seconds=settings.circuit_open_timeout_seconds,
    )


async def call_unstable(url: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=2.0) as client:
        response = await client.get(url)
    if response.status_code >= 500:
        raise UpstreamFailure(response.status_code, response.text)
    response.raise_for_status()
    return response.json()


async def read_fault(redis: Redis) -> dict[str, Any]:
    return {
        "service": "unstable-service",
        "enabled": (await redis.get("fault:unstable-service:enabled")) == "true",
        "error_rate": float(await redis.get("fault:unstable-service:error_rate") or 0),
        "latency_ms": int(await redis.get("fault:unstable-service:latency_ms") or 0),
    }


async def log_event(
    session: AsyncSession,
    service: str,
    event_type: str,
    status_code: int | None = None,
    latency_ms: float | None = None,
    breaker_state: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    session.add(
        TrafficEvent(
            service=service,
            event_type=event_type,
            status_code=status_code,
            latency_ms=latency_ms,
            breaker_state=breaker_state,
            details=details or {},
        )
    )
    await session.commit()
    logger.info(
        "traffic_event_saved",
        service=service,
        event_type=event_type,
        status_code=status_code,
        latency_ms=latency_ms,
        breaker_state=breaker_state,
    )


def elapsed_ms(start: float) -> float:
    return round((perf_counter() - start) * 1000, 2)
