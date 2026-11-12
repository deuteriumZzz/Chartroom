from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from chartroom.bootstrap import Container, build_container
from chartroom.identity.domain import Role
from chartroom.main import create_app
from chartroom.qa.domain import GeneratedAnswer, Passage, RawCitation
from chartroom.shared.config import get_settings
from tests.fakes import RecordingQueue, ScriptedGenerator, StaticPassageRetriever

PASSWORD = "s3cret-pass"
PASSAGES = [
    Passage(1, 7, "Fire", "Fire / 4.4 Engine room", 3, "Close the fuel valves.", 0.031, 0.81),
    Passage(1, 7, "Fire", "Fire / 4.2 Alarm", None, "Sound the general alarm.", 0.016, 0.64),
]
ANSWER = GeneratedAnswer(
    "Закройте быстрозапорные клапаны топлива.",
    citations=(RawCitation(1, "Close the fuel valves"), RawCitation(9, "ghost")),
    refusal=False,
    model="scripted-model",
)
Client = tuple[AsyncClient, Container]


@pytest.fixture
def retriever() -> StaticPassageRetriever:
    return StaticPassageRetriever(PASSAGES)


@pytest.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession], retriever: StaticPassageRetriever
) -> AsyncIterator[Client]:
    container = build_container(
        get_settings(), session_factory, RecordingQueue(), retriever, ScriptedGenerator(ANSWER)
    )
    transport = ASGITransport(app=create_app(container))
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, container


async def _login(client: Client, role: Role, name: str | None = None) -> dict[str, str]:
    http, container = client
    email = f"{name or role}@ship.test"
    await container.identity.register(email, PASSWORD, role)
    r = await http.post("/auth/login", data={"username": email, "password": PASSWORD})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _ask(
    client: Client, headers: dict[str, str], question: str = "Что сделать с топливом?"
) -> int:
    r = await client[0].post("/ask", headers=headers, json={"question": question, "top_k": 2})
    assert r.status_code == 200, r.text
    query_id: int = r.json()["query_id"]
    return query_id


async def test_answer_has_verified_citations_and_flags_the_rest(
    client: Client, retriever: StaticPassageRetriever
) -> None:
    officer = await _login(client, Role.OFFICER)
    r = await client[0].post(
        "/ask", headers=officer, json={"question": "Что сделать с топливом?", "top_k": 2}
    )
    body = r.json()
    assert isinstance(body.pop("query_id"), int)
    assert body == {
        "answer": "Закройте быстрозапорные клапаны топлива.",
        "language": "ru",
        "refusal": False,
        "citation_warning": True,  # ссылка на фрагмент 9 удалена
        "citations": [
            {
                "document_id": 1,
                "version_id": 7,
                "title": "Fire",
                "section_path": "Fire / 4.4 Engine room",
                "page": 3,
                "quote": "Close the fuel valves",
            }
        ],
    }
    assert retriever.calls == [("Что сделать с топливом?", 2)]


async def test_officer_sees_own_history_captain_sees_all(client: Client) -> None:
    first, second = (
        await _login(client, Role.OFFICER, "first"),
        await _login(client, Role.OFFICER, "second"),
    )
    captain = await _login(client, Role.CAPTAIN)
    mine = await _ask(client, first, "Вопрос первого")
    others = await _ask(client, second, "Вопрос второго")

    own = (await client[0].get("/queries", headers=first)).json()
    assert [q["id"] for q in own] == [mine]
    assert (own[0]["question"], own[0]["model"], own[0]["prompt_version"]) == (
        "Вопрос первого",
        "scripted-model",
        "test.v1",
    )
    everyone = (await client[0].get("/queries", headers=captain)).json()
    assert [q["id"] for q in everyone] == [others, mine]
    assert [
        q["id"] for q in (await client[0].get("/queries?limit=1&offset=1", headers=captain)).json()
    ] == [mine]


async def test_feedback_only_on_own_answer(client: Client) -> None:
    officer, stranger = await _login(client, Role.OFFICER), await _login(client, Role.CAPTAIN)
    query_id = await _ask(client, officer)
    path = f"/ask/{query_id}/feedback"

    assert (
        await client[0].post(path, headers=officer, json={"useful": False, "comment": "нет шага"})
    ).status_code == 204
    assert (await client[0].post(path, headers=officer, json={"useful": True})).status_code == 204
    [logged] = (await client[0].get("/queries", headers=officer)).json()
    assert logged["feedback"] == {"useful": True, "comment": None}

    for headers, target in ((stranger, path), (officer, "/ask/999999/feedback")):
        r = await client[0].post(target, headers=headers, json={"useful": True})
        assert (r.status_code, r.json()) == (404, {"detail": "Query not found"})


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", "/ask", {"question": ""}),
        ("POST", "/ask", {"question": "   "}),
        ("POST", "/ask", {"question": "x" * 1001}),
        ("POST", "/ask", {"question": "q", "top_k": 21}),
        ("POST", "/ask/1/feedback", {"useful": True, "comment": "x" * 1001}),
        ("GET", "/queries?limit=0", None),
        ("GET", "/queries?limit=101", None),
        ("GET", "/queries?offset=-1", None),
    ],
)
async def test_invalid_requests_are_422(
    client: Client, method: str, path: str, body: dict[str, object] | None
) -> None:
    officer = await _login(client, Role.OFFICER)
    r = await client[0].request(method, path, headers=officer, json=body)
    assert r.status_code == 422


@pytest.mark.parametrize(
    ("method", "path"), [("POST", "/ask"), ("GET", "/queries"), ("POST", "/ask/1/feedback")]
)
async def test_endpoints_require_authentication(client: Client, method: str, path: str) -> None:
    assert (
        await client[0].request(method, path, json={"question": "q", "useful": True})
    ).status_code == 401


async def test_real_container_refuses_on_empty_library_and_closes(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    for key in ("", "test-key"):
        settings = get_settings().model_copy(update={"gemini_api_key": SecretStr(key)})
        container = build_container(settings, session_factory, RecordingQueue())
        user = await container.identity.register(f"k{len(key)}@ship.test", PASSWORD, Role.OFFICER)
        # В чистой БД нет активных версий: отказ, Gemini и Qdrant не вызываются.
        reply = await container.questions.ask("Что делать при пожаре?", user.id)
        assert (reply.answer.refusal, reply.answer.text) == (
            True,
            "В загруженных документах ответа нет.",
        )
        await container.aclose()
