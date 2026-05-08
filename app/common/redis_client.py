from collections.abc import AsyncGenerator

from redis.asyncio import Redis

from app.common.config import get_settings


def create_redis() -> Redis:
    return Redis.from_url(get_settings().redis_url, decode_responses=True)


async def get_redis() -> AsyncGenerator[Redis, None]:
    client = create_redis()
    try:
        yield client
    finally:
        await client.aclose()
