import os
import uuid
from collections.abc import AsyncIterator

import pytest
from redis.asyncio import Redis

from chartroom.shared.errors import TooManyRequestsError
from chartroom.shared.ratelimit import Policy, RedisRateLimiter

REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/1")


@pytest.fixture
async def redis() -> AsyncIterator[Redis]:
    client = Redis.from_url(REDIS_URL)
    yield client
    await client.aclose()


async def test_requests_over_the_limit_are_rejected_with_the_time_left(redis: Redis) -> None:
    limiter = RedisRateLimiter(redis, {"ask": Policy(2, window_seconds=30)})
    key = uuid.uuid4().hex
    await limiter.hit("ask", key)
    await limiter.hit("ask", key)
    with pytest.raises(TooManyRequestsError) as blocked:
        await limiter.hit("ask", key)
    assert 1 <= blocked.value.retry_after <= 30
    await limiter.hit("ask", uuid.uuid4().hex)  # у другого ключа свой счётчик


async def test_counter_always_expires_so_a_client_is_never_blocked_forever(redis: Redis) -> None:
    limiter = RedisRateLimiter(redis, {"login": Policy(1, window_seconds=30)})
    key = uuid.uuid4().hex
    await limiter.hit("login", key)
    assert 0 < await redis.ttl(f"ratelimit:login:{key}") <= 30


async def test_unreachable_redis_lets_requests_through_and_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    dead = Redis.from_url("redis://localhost:1", socket_connect_timeout=0.2)
    limiter = RedisRateLimiter(dead, {"ask": Policy(1)})
    await limiter.hit("ask", "k")
    await limiter.hit("ask", "k")  # лимит не работает, но сервис отвечает
    assert "rate limiter is unavailable" in caplog.text
    await limiter.aclose()
