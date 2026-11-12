import os

import pytest

from chartroom import bootstrap
from tests.fakes import InMemoryRateLimiter

# Окружение задаётся до первого get_settings(): Settings кешируется (lru_cache).
os.environ.setdefault("JWT_SECRET", "test-only-secret-not-used-anywhere-else-0123456789")
# Фиктивный ключ: в тестах провайдер эмбеддингов всегда подменён, сеть не вызывается.
os.environ.setdefault("GEMINI_API_KEY", "test-only-gemini-key")
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://chartroom:chartroom@localhost:5432/chartroom_test",
)


@pytest.fixture(autouse=True)
def _no_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    """Контейнер в тестах получает лимитер в памяти: тесты не зависят от Redis."""
    monkeypatch.setattr(
        bootstrap, "RedisRateLimiter", lambda _redis, policies: InMemoryRateLimiter(policies)
    )
