from collections.abc import Awaitable, Callable
from time import perf_counter

from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

REQUEST_COUNT = Counter(
    "app_http_requests_total",
    "Total HTTP requests handled by the application.",
    ["app", "method", "path", "status"],
)
REQUEST_LATENCY = Histogram(
    "app_http_request_duration_seconds",
    "HTTP request latency in seconds.",
    ["app", "method", "path"],
)
BREAKER_EVENTS = Counter(
    "control_circuit_breaker_events_total",
    "Circuit breaker state and decision events.",
    ["service", "event", "state"],
)
RETRY_EVENTS = Counter(
    "control_retry_events_total",
    "Retry attempts performed by the control API.",
    ["service", "result"],
)


def setup_metrics(app: FastAPI, app_name: str) -> None:
    @app.middleware("http")
    async def metrics_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        start = perf_counter()
        path = request.scope.get("route").path if request.scope.get("route") else request.url.path
        try:
            response = await call_next(request)
        except Exception:
            REQUEST_COUNT.labels(app_name, request.method, path, "500").inc()
            REQUEST_LATENCY.labels(app_name, request.method, path).observe(perf_counter() - start)
            raise

        REQUEST_COUNT.labels(app_name, request.method, path, str(response.status_code)).inc()
        REQUEST_LATENCY.labels(app_name, request.method, path).observe(perf_counter() - start)
        return response

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
