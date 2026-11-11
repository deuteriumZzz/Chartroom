import os

# Окружение задаётся до первого get_settings(): Settings кешируется (lru_cache).
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://chartroom:chartroom@localhost:5432/chartroom_test",
)
