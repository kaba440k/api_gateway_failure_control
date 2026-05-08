from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "api-gateway-failure-control"
    service_name: str = "generic-service"

    database_url: str
    redis_url: str
    upstream_unstable_url: str

    gateway_url: str = "http://localhost:10000"
    prometheus_url: str = "http://localhost:9090"
    grafana_url: str = "http://localhost:3000"

    circuit_failure_threshold: int = Field(default=3, ge=1)
    circuit_open_timeout_seconds: int = Field(default=10, ge=1)
    retry_attempts: int = Field(default=3, ge=1)
    retry_initial_delay_seconds: float = Field(default=0.2, ge=0)
    retry_max_delay_seconds: float = Field(default=1.5, ge=0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
