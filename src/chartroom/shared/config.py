from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Типизированная конфигурация; секреты приходят только из окружения."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://chartroom:chartroom@localhost:5432/chartroom"


@lru_cache
def get_settings() -> Settings:
    return Settings()
