from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class FaultConfig(BaseModel):
    enabled: bool = True
    error_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    latency_ms: int = Field(default=0, ge=0, le=10000)


class EventOut(BaseModel):
    id: int
    created_at: datetime
    service: str
    event_type: str
    status_code: int | None
    latency_ms: float | None
    breaker_state: str | None
    details: dict[str, Any]


class ProtectedCallOut(BaseModel):
    ok: bool
    breaker_state: str
    status_code: int
    attempts: int
    payload: dict[str, Any] | None = None
    error: str | None = None
