from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Типизированная конфигурация; секреты приходят только из окружения."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://chartroom:chartroom@localhost:5432/chartroom"
    # Без значения по умолчанию: без секрета приложение не стартует, а не работает с известным.
    jwt_secret: SecretStr = Field(min_length=32)
    jwt_ttl_minutes: int = Field(default=60, gt=0)

    redis_url: str = "redis://localhost:6379/0"
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "chunks"
    # Нужен только worker-у индексации: API загружает документы и без него.
    gemini_api_key: SecretStr = SecretStr("")
    embedding_model: str = "gemini-embedding-001"
    embedding_dimensions: int = Field(default=768, ge=128, le=3072)


@lru_cache
def get_settings() -> Settings:
    return Settings()
