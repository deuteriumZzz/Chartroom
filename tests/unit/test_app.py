from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from chartroom.agent.adapters.documents import LibraryDocumentsReader
from chartroom.agent.adapters.reports import ReportServiceReader
from chartroom.agent.service import AgentService
from chartroom.bootstrap import Container
from chartroom.identity.adapters.tokens import JwtTokenService
from chartroom.identity.service import IdentityService
from chartroom.knowledge.service import DocumentLibrary
from chartroom.main import create_app
from chartroom.qa.domain import GeneratedAnswer, RefusalPolicy
from chartroom.qa.service import QuestionService
from chartroom.reports.service import ReportService
from chartroom.shared.errors import DomainError
from chartroom.shared.ratelimit import Policy
from tests.fakes import (
    FakePasswordHasher,
    InMemoryAgentUnitOfWork,
    InMemoryIdentityUnitOfWork,
    InMemoryKnowledgeUnitOfWork,
    InMemoryQaUnitOfWork,
    InMemoryRateLimiter,
    InMemoryReportsUnitOfWork,
    KnowledgeStore,
    QaStore,
    RecordingQueue,
    ReportsStore,
    ScriptedAgentModel,
    ScriptedExtractor,
    ScriptedGenerator,
    StaticPassageRetriever,
    StaticProcedureSearch,
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
    reports = ReportService(
        lambda: InMemoryReportsUnitOfWork(ReportsStore()), ScriptedExtractor({})
    )
    return create_app(
        Container(
            identity=identity,
            library=library,
            questions=questions,
            passages=StaticPassageRetriever([]),
            reports=reports,
            agent=AgentService(
                ScriptedAgentModel([]),
                StaticProcedureSearch([]),
                ReportServiceReader(reports),
                LibraryDocumentsReader(library),
                lambda: InMemoryAgentUnitOfWork([]),
            ),
            limiter=InMemoryRateLimiter({"login": Policy(2)}),
        )
    )


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


async def test_ui_page_and_assets_are_served_with_a_strict_csp(client: AsyncClient) -> None:
    for path in ("/", "/ui/app.js", "/ui/app.css"):
        r = await client.get(path)
        assert r.status_code == 200, path
        assert "default-src 'none'" in r.headers["content-security-policy"]
    page = (await client.get("/")).text
    assert '<script src="/ui/app.js"' in page and "<script>" not in page  # без inline-скриптов


async def test_every_response_has_basic_security_headers(client: AsyncClient) -> None:
    r = await client.get("/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert "content-security-policy" not in r.headers  # CSP только у страницы: Swagger грузит CDN


async def test_login_is_rate_limited_per_client_with_retry_after(client: AsyncClient) -> None:
    attempt = {"username": "ghost@ship.test", "password": "wrong-pass-123"}
    assert [(await client.post("/auth/login", data=attempt)).status_code for _ in range(3)] == [
        401,
        401,
        429,
    ]
    blocked = await client.post("/auth/login", data=attempt)
    assert blocked.headers["retry-after"] == "30" and blocked.json() == {
        "detail": "Too many requests"
    }


async def test_metrics_are_exposed_for_prometheus(client: AsyncClient) -> None:
    await client.get("/health")
    body = (await client.get("/metrics")).text
    assert 'http_requests_total{handler="/health",method="GET",status="2xx"}' in body
