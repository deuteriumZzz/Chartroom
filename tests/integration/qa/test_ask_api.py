from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from chartroom.bootstrap import Container, build_container
from chartroom.identity.domain import Role
from chartroom.main import create_app
from chartroom.qa.domain import Passage
from chartroom.shared.config import get_settings
from tests.fakes import RecordingQueue, StaticPassageRetriever

PASSWORD = "s3cret-pass"
PASSAGES = [
    Passage(1, 7, "Fire", "Fire / 4.4 Engine room", 3, "Close the fuel valves.", 0.031),
    Passage(1, 7, "Fire", "Fire / 4.2 Alarm", None, "Sound the general alarm.", 0.016),
]


@pytest.fixture
def retriever() -> StaticPassageRetriever:
    return StaticPassageRetriever(PASSAGES)


@pytest.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession], retriever: StaticPassageRetriever
) -> AsyncIterator[tuple[AsyncClient, Container]]:
    container = build_container(get_settings(), session_factory, RecordingQueue(), retriever)
    transport = ASGITransport(app=create_app(container))
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, container


async def _officer(client: AsyncClient, container: Container) -> dict[str, str]:
    await container.identity.register("officer@ship.test", PASSWORD, Role.OFFICER)
    r = await client.post(
        "/auth/login", data={"username": "officer@ship.test", "password": PASSWORD}
    )
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_officer_gets_passages_with_citation_data(
    client: tuple[AsyncClient, Container], retriever: StaticPassageRetriever
) -> None:
    http, container = client
    r = await http.post(
        "/ask", headers=await _officer(http, container), json={"question": "fuel?", "top_k": 1}
    )
    assert r.status_code == 200
    assert r.json() == {
        "passages": [
            {
                "document_id": 1,
                "version_id": 7,
                "title": "Fire",
                "section_path": "Fire / 4.4 Engine room",
                "page": 3,
                "text": "Close the fuel valves.",
                "score": 0.031,
            }
        ]
    }
    assert retriever.calls == [("fuel?", 1)]


@pytest.mark.parametrize(
    "body",
    [
        {"question": ""},
        {"question": "   "},
        {"question": "x" * 1001},
        {"question": "q", "top_k": 0},
        {"question": "q", "top_k": 21},
    ],
)
async def test_invalid_requests_are_422(
    client: tuple[AsyncClient, Container], body: dict[str, object]
) -> None:
    http, container = client
    r = await http.post("/ask", headers=await _officer(http, container), json=body)
    assert r.status_code == 422


async def test_ask_requires_authentication(client: tuple[AsyncClient, Container]) -> None:
    http, _ = client
    assert (await http.post("/ask", json={"question": "fire"})).status_code == 401


async def test_real_container_without_key_answers_and_closes(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    for key in ("", "test-key"):
        settings = get_settings().model_copy(update={"gemini_api_key": SecretStr(key)})
        container = build_container(settings, session_factory, RecordingQueue())
        # В чистой БД нет активных версий: ответ пустой, Gemini и Qdrant не вызываются.
        assert await container.questions.ask("fire") == []
        await container.aclose()
