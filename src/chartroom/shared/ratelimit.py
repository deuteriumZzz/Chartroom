"""Ограничение частоты запросов: фиксированное окно в Redis (счётчик на ключ)."""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from redis.asyncio import Redis
from redis.exceptions import RedisError

from chartroom.shared.errors import TooManyRequestsError

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Policy:
    requests: int
    window_seconds: int = 60


class RateLimiter(Protocol):
    async def hit(self, policy: str, key: str) -> None:
        """Засчитывает запрос. Raises TooManyRequestsError, если лимит политики превышен."""
        ...

    async def aclose(self) -> None: ...


class RedisRateLimiter:
    def __init__(self, redis: Redis, policies: Mapping[str, Policy]) -> None:
        self._redis = redis
        self._policies = policies

    async def hit(self, policy: str, key: str) -> None:
        rule = self._policies[policy]
        name = f"ratelimit:{policy}:{key}"
        try:
            # Один MULTI: счётчик и срок жизни не разъезжаются, даже если процесс упадёт между ними.
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.incr(name)
                pipe.expire(name, rule.window_seconds, nx=True)
                pipe.ttl(name)
                count, _, ttl = await pipe.execute()
        except RedisError:
            # Недоступный Redis не должен останавливать весь сервис: пропускаем и пишем в лог.
            logger.warning("rate limiter is unavailable, request allowed", exc_info=True)
            return
        if count > rule.requests:
            raise TooManyRequestsError(max(ttl, 1))

    async def aclose(self) -> None:
        await self._redis.aclose()
