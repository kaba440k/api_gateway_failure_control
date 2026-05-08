# API Gateway Failure Control

Учебно-дипломный прототип по теме: **«Разработка системы контроля и обработки сбоев маршрутизируемого трафика на уровне API-шлюза в распределенной микросервисной архитектуре»**.

Проект показывает минимально достаточную архитектуру: трафик проходит через Envoy, сбойный upstream обрабатывается через `Retry` и `Circuit Breaker`, состояние хранится в Redis, события пишутся в PostgreSQL, метрики собираются Prometheus и отображаются в Grafana.

## Стек

- Envoy Proxy
- FastAPI
- PostgreSQL
- Redis
- Prometheus
- Grafana
- SQLAlchemy
- Alembic
- Tenacity
- Docker Compose
- Poetry

## Конфигурация

Настройки проекта лежат в `.env`. Этот файл не нужно пушить в git: он добавлен в `.gitignore`.

Для передачи проекта другому человеку используется безопасный шаблон:

```powershell
Copy-Item .env.example .env
```

Основные группы настроек:

- порты сервисов: `FRONTEND_PORT`, `ENVOY_GATEWAY_PORT`, `CONTROL_API_PORT`, `PROMETHEUS_PORT`, `GRAFANA_PORT`;
- доступы к PostgreSQL и Grafana: `POSTGRES_*`, `GRAFANA_*`;
- URL для локального запуска: `DATABASE_URL`, `REDIS_URL`, `UPSTREAM_UNSTABLE_URL`;
- URL для Docker-сети: `DATABASE_URL_DOCKER`, `REDIS_URL_DOCKER`, `UPSTREAM_UNSTABLE_URL_DOCKER`;
- параметры отказоустойчивости: `CIRCUIT_FAILURE_THRESHOLD`, `CIRCUIT_OPEN_TIMEOUT_SECONDS`, `RETRY_ATTEMPTS`.

## Запуск

```powershell
docker compose up -d --build
```

При запуске Compose сначала выполняет сервис `migrate`, который применяет Alembic-миграции к PostgreSQL. После этого стартует `control-api`.

Открыть:

- Frontend: http://localhost:8080
- Envoy gateway: http://localhost:10000
- Control API: http://localhost:8000
- Envoy admin: http://localhost:9901
- Prometheus targets: http://localhost:9090/targets
- Grafana dashboard: http://localhost:3000/d/failure-control/api-gateway-failure-control?orgId=1&refresh=5s

Логин и пароль Grafana задаются через `GRAFANA_ADMIN_USER` и `GRAFANA_ADMIN_PASSWORD` в `.env`.

## Демонстрация

Самый удобный путь: открыть http://localhost:8080 и нажать `Запустить сценарий сбоя`.

Что демонстрируется:

1. Успешный protected call к `unstable-service`.
2. Включение управляемого сбоя через Fault Injection.
3. Несколько попыток запроса с retry/backoff.
4. Накопление ошибок и переход Circuit Breaker в `OPEN`.
5. Быстрое отклонение следующих запросов без обращения к upstream.
6. Запись событий в PostgreSQL и публикация метрик для Prometheus/Grafana.

## Полезные команды

Проверить состояние:

```powershell
docker compose ps
```

Посмотреть логи:

```powershell
docker compose logs -f control-api
```

Запустить unit-тесты локально:

```powershell
poetry run pytest
```

Запустить smoke-сценарий через Envoy:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\smoke-test.ps1
```

Применить миграции вручную:

```powershell
docker compose run --rm migrate
```

Остановить стенд:

```powershell
docker compose down
```

Полная очистка БД и Grafana-данных:

```powershell
docker compose down -v
```
