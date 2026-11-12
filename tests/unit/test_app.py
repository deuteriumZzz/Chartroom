from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from chartroom.bootstrap import Container
from chartroom.identity.adapters.tokens import JwtTokenService
from chartroom.identity.service import IdentityService
from chartroom.knowledge.service import DocumentLibrary
from chartroom.main import create_app
from chartroom.qa.domain import GeneratedAnswer, RefusalPolicy
from chartroom.qa.service import QuestionService
from chartroom.shared.errors import DomainError
from tests.fakes import (
    FakePasswordHasher,
    InMemoryIdentityUnitOfWork,
    InMemoryKnowledgeUnitOfWork,
    InMemoryQaUnitOfWork,
    KnowledgeStore,
    QaStore,
    RecordingQueue,
    ScriptedGenerator,
    StaticPassageRetriever,
)


@pytest.fixture
def app() -> FastAPI:
    identity = IdentityService(
        lambda: InMemoryIdentityUnitOfWork({}),
        FakePasswordHasher(),
        JwtTokenService("unit-test-secret-that-is-long-enough-0123456789", timedelta(minutes=5)),
    )
    store = KnowledgeStore()
    library = DocumentLibrary(lambda: InMemoryKnowledgeUnitOfWork(store), RecordingQueue())
    questions = QuestionService(
        StaticPassageRetriever([]),
        ScriptedGenerator(GeneratedAnswer("", (), refusal=True, model="scripted-model")),
        RefusalPolicy(min_similarity=0.5),
        lambda: InMemoryQaUnitOfWork(QaStore()),
    )
    return create_app(Container(identity=identity, library=library, questions=questions))


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_health(client: AsyncClient) -> None:
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_uncategorized_domain_error_maps_to_400(app: FastAPI, client: AsyncClient) -> None:
    @app.get("/probe")
    async def probe() -> None:
        raise DomainError

    r = await client.get("/probe")
    assert r.status_code == 400
    assert r.json() == {"detail": "Request cannot be processed"}


async def test_shutdown_releases_resources(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    closed: list[bool] = []

    async def fake_aclose(_: Container) -> None:
        closed.append(True)

    monkeypatch.setattr(Container, "aclose", fake_aclose)
    async with app.router.lifespan_context(app):  # ASGITransport сам lifespan не запускает
        assert closed == []
    assert closed == [True]
