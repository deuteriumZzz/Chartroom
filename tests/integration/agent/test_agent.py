from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from chartroom.agent.adapters.persistence import AgentRunRecord, ToolCallRecord
from chartroom.agent.domain import ModelTurn, ToolCall
from chartroom.bootstrap import Container, build_container
from chartroom.identity.domain import Role
from chartroom.main import create_app
from chartroom.qa.domain import Passage
from chartroom.shared.config import get_settings
from tests.fakes import RecordingQueue, ScriptedAgentModel, StaticPassageRetriever

PASSAGE = Passage(
    1, 7, "Fire", "Fire / 4.4 Engine room", None, "Close the fuel valves before CO2.", 0.03, 0.8
)
PASSWORD = "s3cret-pass"


@pytest.fixture
async def http(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[tuple[AsyncClient, Container]]:
    model = ScriptedAgentModel(
        [
            ModelTurn(
                (ToolCall("search_procedures", {"query": "CO2"}), ToolCall("list_reports", {})),
                None,
            ),
            ModelTurn(
                (
                    ToolCall(
                        "submit_answer",
                        {
                            "answer": "Закройте клапаны.",
                            "refusal": False,
                            "citations": [
                                {"passage": 1, "quote": "Close the fuel valves"},
                                {"passage": 9, "quote": "ghost"},
                            ],
                        },
                    ),
                ),
                None,
            ),
        ]
    )
    container = build_container(
        get_settings(),
        session_factory,
        RecordingQueue(),
        retriever=StaticPassageRetriever([PASSAGE]),
        agent_model=model,
    )
    async with AsyncClient(
        transport=ASGITransport(app=create_app(container)), base_url="http://test"
    ) as client:
        yield client, container


async def test_agent_answers_over_http_and_audits_every_tool_call(
    http: tuple[AsyncClient, Container], session_factory: async_sessionmaker[AsyncSession]
) -> None:
    client, container = http
    await container.identity.register("officer@ship.test", PASSWORD, Role.OFFICER)
    token = (
        await client.post(
            "/auth/login", data={"username": "officer@ship.test", "password": PASSWORD}
        )
    ).json()["access_token"]
    r = await client.post(
        "/agent/ask",
        headers={"Authorization": f"Bearer {token}"},
        json={"question": "Кто пускает CO2?"},
    )

    body = r.json()
    assert r.status_code == 200
    assert (body["answer"], body["language"], body["refusal"], body["citation_warning"]) == (
        "Закройте клапаны.",
        "ru",
        False,
        True,
    )
    assert [c["quote"] for c in body["citations"]] == ["Close the fuel valves"]
    assert [(c["step"], c["name"], c["ok"]) for c in body["tool_calls"]] == [
        (1, "search_procedures", True),
        (1, "list_reports", True),
    ]
    async with session_factory() as session:
        run = await session.get_one(AgentRunRecord, body["run_id"])
        calls = await session.scalar(select(func.count()).where(ToolCallRecord.run_id == run.id))
    assert (run.steps, run.model, run.prompt_version, calls) == (
        2,
        "scripted-agent",
        "agent.test",
        2,
    )


async def test_agent_requires_authentication_and_a_question(
    http: tuple[AsyncClient, Container],
) -> None:
    client, _ = http
    assert (await client.post("/agent/ask", json={"question": "q"})).status_code == 401
