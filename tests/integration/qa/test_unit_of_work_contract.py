"""Контракт журнала запросов: фейк и Postgres ведут себя одинаково."""

from collections.abc import Callable

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from chartroom.identity.adapters.persistence import SqlIdentityUnitOfWork
from chartroom.identity.domain import Role
from chartroom.qa.adapters.persistence import SqlQaUnitOfWork
from chartroom.qa.domain import Answer, Citation, Feedback, QueryEntry
from chartroom.qa.ports import QaUnitOfWork
from chartroom.shared.language import Language
from tests.fakes import InMemoryQaUnitOfWork, QaStore

UowFactory = Callable[[], QaUnitOfWork]
CITATIONS = (
    Citation(1, 7, "Fire", "Fire / 4.4", 2, "закрывают клапаны топлива"),
    Citation(1, 7, "Fire", "Fire / 4.2", None, "громкий бой"),
)
ANSWER = Answer("Закрыть клапаны.", Language.RU, False, CITATIONS, citation_warning=True)


@pytest.fixture(params=["in-memory", "sql"])
async def world(
    request: pytest.FixtureRequest, session_factory: async_sessionmaker[AsyncSession]
) -> tuple[UowFactory, int, int]:
    if request.param == "in-memory":
        store = QaStore()
        return (lambda: InMemoryQaUnitOfWork(store)), 1, 2
    async with SqlIdentityUnitOfWork(session_factory) as identity:  # журнал ссылается на users
        first = await identity.users.add("a@ship.test", "h", Role.OFFICER)
        second = await identity.users.add("b@ship.test", "h", Role.CAPTAIN)
        await identity.commit()
    return (lambda: SqlQaUnitOfWork(session_factory)), first.id, second.id


def _entry(user_id: int, question: str = "Что делать?") -> QueryEntry:
    return QueryEntry(
        user_id, question, ANSWER, latency_ms=812, model="m", prompt_version="answer.v2"
    )


async def test_logged_query_round_trips_with_citations_in_order(
    world: tuple[UowFactory, int, int],
) -> None:
    uow_factory, user, _ = world
    async with uow_factory() as uow:
        query_id = await uow.queries.add(_entry(user))
        await uow.commit()
    async with uow_factory() as uow:
        logged = await uow.queries.get(query_id)
        assert await uow.queries.get(query_id + 1000) is None
    assert logged is not None
    assert (logged.user_id, logged.question, logged.answer, logged.feedback) == (
        user,
        "Что делать?",
        ANSWER,
        None,
    )
    assert (logged.latency_ms, logged.model, logged.prompt_version) == (812, "m", "answer.v2")
    assert logged.created_at.tzinfo is not None


async def test_history_is_newest_first_filtered_and_paged(
    world: tuple[UowFactory, int, int],
) -> None:
    uow_factory, first, second = world
    async with uow_factory() as uow:
        ids = [
            await uow.queries.add(_entry(user, f"q{n}"))
            for n, user in enumerate([first, second, first])
        ]
        await uow.commit()
    async with uow_factory() as uow:
        assert [q.id for q in await uow.queries.list(None, limit=10, offset=0)] == ids[::-1]
        assert [q.id for q in await uow.queries.list(first, limit=10, offset=0)] == [ids[2], ids[0]]
        assert [q.id for q in await uow.queries.list(None, limit=1, offset=1)] == [ids[1]]


async def test_feedback_is_replaced_not_duplicated(world: tuple[UowFactory, int, int]) -> None:
    uow_factory, user, _ = world
    async with uow_factory() as uow:
        query_id = await uow.queries.add(_entry(user))
        await uow.feedback.save(query_id, Feedback(False, "нет шага"))
        await uow.commit()
    async with uow_factory() as uow:
        await uow.feedback.save(query_id, Feedback(True, None))
        await uow.commit()
    async with uow_factory() as uow:
        logged = await uow.queries.get(query_id)
    assert logged is not None and logged.feedback == Feedback(True, None)


async def test_uncommitted_query_is_discarded(world: tuple[UowFactory, int, int]) -> None:
    uow_factory, user, _ = world
    async with uow_factory() as uow:
        await uow.queries.add(_entry(user))
    async with uow_factory() as uow:
        assert await uow.queries.list(None, limit=10, offset=0) == []
