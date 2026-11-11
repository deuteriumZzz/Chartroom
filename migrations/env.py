import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

import chartroom.identity.adapters.persistence  # noqa: F401  регистрирует таблицы модуля в Base
import chartroom.knowledge.adapters.persistence  # noqa: F401
import chartroom.qa.adapters.persistence  # noqa: F401
from chartroom.shared.config import get_settings
from chartroom.shared.database import Base

target_metadata = Base.metadata


def _run(connection) -> None:  # type: ignore[no-untyped-def]
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def _run_online() -> None:
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as conn:
        await conn.run_sync(_run)
    await engine.dispose()


asyncio.run(_run_online())
