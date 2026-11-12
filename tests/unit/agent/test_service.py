from typing import Any

import pytest

from chartroom.agent.domain import (
    MAX_STEPS,
    NO_DATA_TEXT,
    AgentRun,
    AgentViewer,
    ModelTurn,
    Source,
    ToolCall,
)
from chartroom.agent.service import AgentService
from chartroom.reports.domain import ReportNotFoundError, TemplateNotFoundError
from chartroom.shared.language import Language
from tests.fakes import InMemoryAgentUnitOfWork, ScriptedAgentModel, StaticProcedureSearch

OFFICER = AgentViewer(7, is_supervisor=False)
FIRE = Source(
    0, 1, 7, "Fire", "Fire / 4.4 Engine room", None, "Close the fuel valves before releasing CO2."
)


class FakeReports:
    """Отчёт 5 принадлежит пользователю 7; чужие и несуществующие — ReportNotFoundError."""

    def __init__(self) -> None:
        self.viewers: list[AgentViewer] = []

    async def list_reports(
        self, viewer: AgentViewer, status: str | None, template: str | None, limit: int
    ) -> list[dict[str, Any]]:
        self.viewers.append(viewer)
        return [
            {"report_id": 5, "status": status or "needs_review", "template": template, "issues": 1}
        ]

    async def get_report(self, viewer: AgentViewer, report_id: int) -> dict[str, Any]:
        self.viewers.append(viewer)
        if report_id != 5 or viewer.user_id != 7:
            raise ReportNotFoundError
        return {"report_id": 5, "issues": [{"field": "crew_present", "message": "required"}]}

    async def get_template(self, name: str) -> dict[str, Any]:
        if name != "drill_checklist":
            raise TemplateNotFoundError
        return {"name": name, "required": ["crew_present"]}


class FakeDocuments:
    async def active_version(self, title: str) -> dict[str, Any]:
        return {"title": title, "active_version": "3", "issued_on": "2026-09-01"}


def _agent(
    turns: list[ModelTurn], search: StaticProcedureSearch | None = None
) -> tuple[AgentService, ScriptedAgentModel, list[AgentRun], FakeReports]:
    model, reports = ScriptedAgentModel(turns), FakeReports()
    runs: list[AgentRun] = []
    service = AgentService(
        model,
        search or StaticProcedureSearch([FIRE]),
        reports,
        FakeDocuments(),
        lambda: InMemoryAgentUnitOfWork(runs),
    )
    return service, model, runs, reports


def _call(name: str, **args: Any) -> ModelTurn:
    return ModelTurn((ToolCall(name, args),), None)


async def test_search_then_answer_with_a_verified_citation_is_logged() -> None:
    service, model, runs, _ = _agent(
        [
            _call("search_procedures", query="CO2 engine room fire"),
            _call(
                "submit_answer",
                answer="Закройте клапаны топлива.",
                refusal=False,
                citations=[{"passage": 1, "quote": "Close the fuel valves"}],
            ),
        ]
    )
    reply = await service.ask("  Кто пускает CO2? ", OFFICER)

    answer = reply.answer
    assert (answer.refusal, answer.language, answer.citation_warning, answer.steps) == (
        False,
        Language.RU,
        False,
        2,
    )
    assert [c.quote for c in answer.citations] == ["Close the fuel valves"]
    assert [(c.step, c.name, c.ok) for c in reply.tool_calls] == [(1, "search_procedures", True)]
    passages = model.conversation.received[1][0].content["passages"]
    assert passages == [
        {"passage": 1, "document": "Fire", "section": "Fire / 4.4 Engine room", "text": FIRE.text}
    ]
    [run] = runs
    assert (reply.run_id, run.user_id, run.question, run.model, run.prompt_version) == (
        1,
        7,
        "Кто пускает CO2?",
        "scripted-agent",
        "agent.test",
    )


async def test_bad_calls_come_back_to_the_model_as_errors() -> None:
    service, model, _, _ = _agent(
        [
            ModelTurn(
                (
                    ToolCall("delete_report", {"report_id": 5}),
                    ToolCall("get_report", {"report_id": "five"}),
                    ToolCall("search_procedures", {"query": "x", "user_id": 99}),
                ),
                None,
            ),
            _call("submit_answer", answer="Нет данных", refusal=True),
        ]
    )
    reply = await service.ask("Удали отчёт 5", OFFICER)
    errors = [r.content["error"] for r in model.conversation.received[1]]
    assert errors == [
        "Unknown tool: delete_report",
        "Invalid arguments: report_id must be an integer",
        "Invalid arguments: user_id unknown field",  # чужого пользователя не подставить
    ]
    assert [c.ok for c in reply.tool_calls] == [False, False, False]
    assert reply.answer.refusal


async def test_tools_act_as_the_token_user_and_someone_elses_report_is_not_found() -> None:
    service, model, _, reports = _agent(
        [
            ModelTurn(
                (
                    ToolCall("get_report", {"report_id": 6}),
                    ToolCall("get_report", {"report_id": 5}),
                    ToolCall("list_reports", {"status": "needs_review"}),
                ),
                None,
            ),
            _call("submit_answer", answer="Отчёт 5: не заполнено crew_present.", refusal=False),
        ]
    )
    reply = await service.ask("Что не так с моими отчётами?", OFFICER)
    results = model.conversation.received[1]
    assert results[0].content == {"error": "Report not found"} and not results[0].ok
    assert results[1].content["report"]["issues"] == [
        {"field": "crew_present", "message": "required"}
    ]
    assert results[2].content["reports"][0]["status"] == "needs_review"
    assert set(reports.viewers) == {OFFICER}
    assert reply.answer.text == "Отчёт 5: не заполнено crew_present."


async def test_template_and_document_tools() -> None:
    service, model, _, _ = _agent(
        [
            ModelTurn(
                (
                    ToolCall("get_report_template", {"name": "drill_checklist"}),
                    ToolCall("get_report_template", {"name": "nope"}),
                    ToolCall("get_active_document_version", {"title": "Fire"}),
                ),
                None,
            ),
            _call("submit_answer", answer="ok", refusal=False),
        ]
    )
    await service.ask("Какие поля обязательны?", OFFICER)
    results = model.conversation.received[1]
    assert results[0].content["template"]["required"] == ["crew_present"]
    assert results[1].content == {"error": "Report template not found"}
    assert results[2].content["document"]["active_version"] == "3"


async def test_step_limit_ends_with_an_honest_no_data_answer() -> None:
    service, _, runs, _ = _agent([_call("search_procedures", query="loop")] * (MAX_STEPS + 2))
    reply = await service.ask("What is the meaning of life?", OFFICER)
    assert (reply.answer.refusal, reply.answer.text, reply.answer.steps) == (
        True,
        NO_DATA_TEXT[Language.EN],
        MAX_STEPS,
    )
    assert len(reply.tool_calls) == MAX_STEPS and len(runs) == 1


async def test_malformed_submission_is_returned_and_can_be_corrected() -> None:
    service, model, _, _ = _agent(
        [
            _call("submit_answer", answer=42, refusal=False),
            _call("submit_answer", answer="Fixed.", refusal=False),
        ]
    )
    reply = await service.ask("q?", OFFICER)
    assert model.conversation.received[1][0].content == {
        "error": "submit_answer needs a string 'answer' and a boolean 'refusal'"
    }
    assert (reply.answer.text, [c.ok for c in reply.tool_calls]) == ("Fixed.", [False])


@pytest.mark.parametrize(
    ("text", "refusal"), [("Plain text answer.", False), ("   ", True), (None, True)]
)
async def test_plain_text_turn_ends_the_run(text: str | None, refusal: bool) -> None:
    service, _, _, _ = _agent([ModelTurn((), text)])
    reply = await service.ask("q?", OFFICER)
    assert reply.answer.refusal is refusal and reply.answer.citations == ()


async def test_unavailable_tool_is_an_error_result() -> None:
    service, model, _, _ = _agent(
        [
            _call("search_procedures", query="fire"),
            _call("submit_answer", answer="x", refusal=True),
        ],
        search=StaticProcedureSearch([], unavailable=True),
    )
    await service.ask("fire?", OFFICER)
    assert model.conversation.received[1][0].content == {"error": "Tool is temporarily unavailable"}


async def test_search_query_is_capped_and_top_k_defaults() -> None:
    search = StaticProcedureSearch([FIRE])
    service, _, _, _ = _agent(
        [
            _call("search_procedures", query="x" * 900),
            _call("submit_answer", answer="x", refusal=True),
        ],
        search,
    )
    await service.ask("q?", OFFICER)
    assert search.queries == [("x" * 500, 5)]
