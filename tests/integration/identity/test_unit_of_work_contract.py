"""Один контракт — две реализации. Если фейк и SQL-адаптер разойдутся в поведении,
unit-тесты на фейках перестанут что-либо доказывать; этот набор ловит такое расхождение."""

from collections.abc import Callable

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from chartroom.identity.adapters.persistence import SqlIdentityUnitOfWork
from chartroom.identity.domain import EmailAlreadyRegisteredError, Role, User
from chartroom.identity.ports import IdentityUnitOfWork
from tests.fakes import InMemoryIdentityUnitOfWork

UowFactory = Callable[[], IdentityUnitOfWork]


@pytest.fixture(params=["in-memory", "sql"])
def uow_factory(
    request: pytest.FixtureRequest, session_factory: async_sessionmaker[AsyncSession]
) -> UowFactory:
    if request.param == "sql":
        return lambda: SqlIdentityUnitOfWork(session_factory)
    store: dict[int, User] = {}
    return lambda: InMemoryIdentityUnitOfWork(store)


async def test_committed_user_is_readable_in_next_unit_of_work(uow_factory: UowFactory) -> None:
    async with uow_factory() as uow:
        added = await uow.users.add("a@ship.test", "hash", Role.CAPTAIN)
        await uow.commit()
    async with uow_factory() as uow:
        assert await uow.users.get(added.id) == added
        assert await uow.users.get_by_email("a@ship.test") == added


async def test_changes_without_commit_are_discarded(uow_factory: UowFactory) -> None:
    async with uow_factory() as uow:
        await uow.users.add("a@ship.test", "hash", Role.OFFICER)
    async with uow_factory() as uow:
        assert await uow.users.get_by_email("a@ship.test") is None


async def test_duplicate_email_rejected(uow_factory: UowFactory) -> None:
    async with uow_factory() as uow:
        await uow.users.add("a@ship.test", "hash", Role.OFFICER)
        await uow.commit()
    async with uow_factory() as uow:
        with pytest.raises(EmailAlreadyRegisteredError):
            await uow.users.add("a@ship.test", "hash", Role.ADMIN)


async def test_missing_user_is_none(uow_factory: UowFactory) -> None:
    async with uow_factory() as uow:
        assert await uow.users.get(999) is None
