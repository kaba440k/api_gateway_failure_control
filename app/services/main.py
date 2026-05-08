import asyncio
import random
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.common.config import get_settings
from app.common.metrics import setup_metrics
from app.common.redis_client import create_redis


def create_app() -> FastAPI:
    settings = get_settings()
    service_name = settings.service_name
    app = FastAPI(title=service_name, version="0.1.0")
    redis = create_redis()
    setup_metrics(app, service_name)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("shutdown")
    async def shutdown() -> None:
        await redis.aclose()

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"service": service_name, "status": "ok"}

    @app.get("/orders")
    async def orders() -> dict[str, object]:
        return {
            "service": service_name,
            "order_id": str(uuid4()),
            "status": "created",
            "created_at": datetime.now(UTC).isoformat(),
        }

    @app.get("/payments")
    async def payments() -> dict[str, object]:
        return {
            "service": service_name,
            "payment_id": str(uuid4()),
            "status": "authorized",
            "authorized_at": datetime.now(UTC).isoformat(),
        }

    @app.get("/unstable")
    async def unstable() -> dict[str, object]:
        enabled = await redis.get("fault:unstable-service:enabled")
        latency_ms = int(await redis.get("fault:unstable-service:latency_ms") or 0)
        error_rate = float(await redis.get("fault:unstable-service:error_rate") or 0)

        if latency_ms > 0:
            await asyncio.sleep(latency_ms / 1000)

        if enabled == "true" and random.random() < error_rate:
            raise HTTPException(status_code=503, detail="Injected unstable-service failure")

        return {
            "service": service_name,
            "request_id": str(uuid4()),
            "status": "ok",
            "fault_enabled": enabled == "true",
            "error_rate": error_rate,
            "latency_ms": latency_ms,
            "handled_at": datetime.now(UTC).isoformat(),
        }

    return app
