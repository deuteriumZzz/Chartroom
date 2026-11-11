import os

# Окружение задаётся до первого get_settings(): Settings кешируется (lru_cache).
os.environ.setdefault("JWT_SECRET", "test-only-secret-not-used-anywhere-else-0123456789")
# Фиктивный ключ: в тестах провайдер эмбеддингов всегда подменён, сеть не вызывается.
os.environ.setdefault("GEMINI_API_KEY", "test-only-gemini-key")
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://chartroom:chartroom@localhost:5432/chartroom_test",
)
