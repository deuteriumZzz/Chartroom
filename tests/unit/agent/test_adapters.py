from datetime import date
from types import SimpleNamespace
from typing import Any, cast

import pytest
from google import genai
from google.genai import types

from chartroom.agent.adapters.documents import LibraryDocumentsReader
from chartroom.agent.adapters.gemini import GeminiAgentModel, UnconfiguredAgentModel
from chartroom.agent.adapters.reports import ReportServiceReader
from chartroom.agent.adapters.search import QaProcedureSearch
from chartroom.agent.domain import AgentViewer, Source, ToolResult
from chartroom.knowledge.domain.models import DocumentUpload
from chartroom.knowledge.service import DocumentLibrary
from chartroom.qa.domain import Passage
from chartroom.reports.domain import ReportNotFoundError, TemplateNotFoundError
from chartroom.reports.service import ReportService
from chartroom.shared.errors import ServiceUnavailableError
from chartroom.shared.language import Language
from tests.fakes import (
    InMemoryKnowledgeUnitOfWork,
    InMemoryReportsUnitOfWork,
    KnowledgeStore,
    RecordingQueue,
    ReportsStore,
    ScriptedExtractor,
    StaticPassageRetriever,
)


def _response(*parts: types.Part) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=list(parts)))]
    )


class StubModels:
    def __init__(self, responses: list[Any]) -> None:
        self.calls: list[dict[str, Any]] = []
        self._responses = responses

    async def generate_content(self, **kwargs: Any) -> Any:
        self.calls.append({**kwargs, "contents": list(kwargs["contents"])})
        outcome = self._responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


async def test_gemini_conversation_sends_declarations_and_function_responses() -> None:
    from google.genai import errors

    call = types.Part(
        function_call=types.FunctionCall(name="search_procedures", args={"query": "CO2"})
    )
    models = StubModels(
        [
            errors.ServerError(503, {"error": {"message": "busy"}}),
            _response(call),
            _response(types.Part.from_text(text="Done.")),
        ]
    )
    client = cast(genai.Client, SimpleNamespace(aio=SimpleNamespace(models=models)))
    agent = GeminiAgentModel(client, ["busy-model", "good-model"])
    conversation = agent.start("Кто пускает <CO2>?", Language.RU)

    first = await conversation.next_turn([])
    assert [(c.name, c.args) for c in first.calls] == [("search_procedures", {"query": "CO2"})]
    assert conversation.model == "good-model"
    declared = [d.name for d in models.calls[0]["config"].tools[0].function_declarations]
    assert declared[-1] == "submit_answer" and "search_procedures" in declared
    assert "&lt;CO2&gt;" in models.calls[0]["contents"][0].parts[0].text

    second = await conversation.next_turn([ToolResult("search_procedures", {"passages": []}, True)])
    assert (second.calls, second.text) == ((), "Done.")
    assert models.calls[-1]["model"] == "good-model"  # диалог закреплён за ответившей моделью
    history = models.calls[-1]["contents"]
    assert history[1].parts[0].function_call.name == "search_procedures"  # ход модели — как есть
    assert history[2].parts[0].function_response.response == {"passages": []}
    assert agent.prompt_version == "agent.v1"


def test_agent_model_needs_at_least_one_model() -> None:
    with pytest.raises(ValueError):
        GeminiAgentModel(cast(genai.Client, SimpleNamespace()), [])


async def test_unconfigured_agent_is_service_unavailable() -> None:
    conversation = UnconfiguredAgentModel().start("q", Language.EN)
    with pytest.raises(ServiceUnavailableError):
        await conversation.next_turn([])
    assert conversation.model is None


async def test_search_bridge_maps_passages() -> None:
    passage = Passage(1, 7, "Fire", "Fire / 4.4", 3, "Close the valves.", 0.03, 0.8)
    assert await QaProcedureSearch(StaticPassageRetriever([passage])).search("fire", 5) == [
        Source(0, 1, 7, "Fire", "Fire / 4.4", 3, "Close the valves.")
    ]


async def test_reports_bridge_respects_ownership() -> None:
    schema = {
        "type": "object",
        "properties": {"crew_total": {"type": "integer", "title": "Экипаж"}},
        "required": ["crew_total"],
    }
    store = ReportsStore()
    service = ReportService(
        lambda: InMemoryReportsUnitOfWork(store), ScriptedExtractor({"crew_total": None})
    )
    await service.create_template("drill_checklist", "Drill", schema)
    report = await service.extract("drill_checklist", "text", user_id=7)
    reader = ReportServiceReader(service)
    me, stranger, captain = AgentViewer(7, False), AgentViewer(8, False), AgentViewer(1, True)

    [summary] = await reader.list_reports(me, "needs_review", "drill_checklist", 10)
    assert (summary["report_id"], summary["template"], summary["issues"]) == (
        report.id,
        "drill_checklist",
        1,
    )
    assert await reader.list_reports(stranger, None, None, 10) == []
    assert len(await reader.list_reports(captain, None, None, 10)) == 1
    detail = await reader.get_report(me, report.id)
    assert detail["issues"] == [{"field": "crew_total", "message": "required"}]
    with pytest.raises(ReportNotFoundError):
        await reader.get_report(stranger, report.id)
    template = await reader.get_template("drill_checklist")
    assert (template["fields"], template["required"]) == ({"crew_total": "Экипаж"}, ["crew_total"])
    with pytest.raises(TemplateNotFoundError):
        await reader.get_template("nope")


async def test_documents_bridge_reports_the_active_revision() -> None:
    from dataclasses import replace

    store = KnowledgeStore()
    library = DocumentLibrary(lambda: InMemoryKnowledgeUnitOfWork(store), RecordingQueue())
    version = await library.upload(
        DocumentUpload("Fire", Language.EN, "3", date(2026, 9, 1), "fire.md", b"# Fire")
    )
    assert await LibraryDocumentsReader(library).active_version("fire") == {
        "title": "Fire",
        "language": "en",
        "active_version": None,
        "issued_on": None,
    }
    store.versions[version.id] = replace(store.versions[version.id], is_active=True)
    assert (await LibraryDocumentsReader(library).active_version("fire"))["active_version"] == "3"


async def test_response_without_candidates_is_an_empty_turn() -> None:
    """Например, ответ заблокирован фильтром безопасности: агент скажет «нет данных»."""
    models = StubModels([types.GenerateContentResponse(candidates=[])])
    client = cast(genai.Client, SimpleNamespace(aio=SimpleNamespace(models=models)))
    turn = await GeminiAgentModel(client, ["m"]).start("q", Language.EN).next_turn([])
    assert (turn.calls, turn.text) == ((), None)
