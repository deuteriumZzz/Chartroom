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
    # Цепочка моделей: при перегрузке провайдера (5xx, 429, таймаут) — следующая.
    # В окружении — JSON-список: GENERATION_MODELS='["gemini-3.6-flash","gemini-3.5-flash"]'.
    generation_models: list[str] = Field(
        default=["gemini-3.6-flash", "gemini-3.5-flash"], min_length=1
    )
    # Запросов в минуту: на вход — с одного IP, на вопросы (/ask, /agent/ask) — от пользователя.
    login_rate_limit: int = Field(default=10, gt=0)
    ask_rate_limit: int = Field(default=20, gt=0)
    # Порог сходства лучшего фрагмента с вопросом, ниже которого — отказ без вызова модели.
    # Откалиброван на золотом наборе (ADR-010): вопросы без ответа — до 0.632, с ответом — от 0.658.
    refusal_min_similarity: float = Field(default=0.64, ge=0.0, le=1.0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
