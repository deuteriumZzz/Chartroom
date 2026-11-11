from typing import Any

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

import chartroom.identity.adapters.persistence
import chartroom.knowledge.adapters.persistence  # noqa: F401  регистрируют таблицы в Base
from chartroom.shared.database import Base


def _schema_diff(connection: Connection) -> list[Any]:
    return list(compare_metadata(MigrationContext.configure(connection), Base.metadata))


async def test_migrations_match_orm_models(engine: AsyncEngine) -> None:
    # Схему в engine построили миграции (conftest). Любое расхождение с моделями — забытая миграция.
    async with engine.connect() as connection:
        assert await connection.run_sync(_schema_diff) == []
