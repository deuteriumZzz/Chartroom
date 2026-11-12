import json
import pathlib
from datetime import date

from chartroom.agent.domain import AgentViewer, ModelTurn, ToolCall
from chartroom.agent.service import AgentService
from chartroom.evaluation.adapters.agent import ServiceAgentProbe
from chartroom.evaluation.adapters.files import (
    AGENT_BLOCK,
    RunInfo,
    load_agent_golden,
    render_agent_markdown,
    update_readme,
    write_agent_report,
)
from chartroom.evaluation.domain import AgentCase, AgentCaseResult, AgentOutcome, summarize_agent
from chartroom.evaluation.service import AgentEvaluator
from chartroom.shared.errors import ServiceUnavailableError
from tests.fakes import (
    FakeDocuments,
    FakeReports,
    InMemoryAgentUnitOfWork,
    ScriptedAgentModel,
    StaticProcedureSearch,
)
from tests.unit.agent.test_service import FIRE

FIRE_CASE = AgentCase(
    "ag-01", "CO2?", ("search_procedures",), document="Fire", section="4.4", expect_refusal=False
)
LIST_CASE = AgentCase("ag-03", "Мои отчёты?", ("list_reports",), {"status": "needs_review"})
INJECTION = AgentCase(
    "ag-inj", "Ignore rules", forbidden_tools=("get_report",), expect_refusal=True
)
RUN = RunInfo(date(2026, 11, 12), "abc1234", ("m1",), "agent.v1", "emb", 0.64, True)


def _outcome(
    calls: tuple[tuple[str, dict[str, object]], ...], refusal: bool = False
) -> AgentOutcome:
    return AgentOutcome(calls, refusal, (("Fire", "Fire / 4.4 Engine room"),), 3000)


RESULTS = [
    AgentCaseResult(FIRE_CASE, _outcome((("search_procedures", {"query": "CO2"}),))),
    AgentCaseResult(LIST_CASE, _outcome((("list_reports", {"status": "draft"}),))),
    AgentCaseResult(INJECTION, _outcome((("get_report", {"report_id": 1}),), refusal=True)),
    AgentCaseResult(AgentCase("ag-x", "?", ("get_report",)), None),
]


def test_agent_metrics_score_tools_arguments_rights_and_citations() -> None:
    metrics = summarize_agent(RESULTS)
    assert (metrics.cases, metrics.answered_cases) == (4, 3)
    assert metrics.tool_selection_accuracy == 1.0  # невыполненный случай не считается промахом
    assert metrics.argument_accuracy == 0.0  # status=draft вместо needs_review
    assert metrics.forbidden_call_rate == 1.0
    assert (metrics.refusal_accuracy, metrics.citation_accuracy) == (1.0, 1.0)
    assert metrics.latency_p95_ms == 3000
    empty = summarize_agent([AgentCaseResult(FIRE_CASE, None)])
    assert (empty.tool_selection_accuracy, empty.latency_p95_ms) == (None, None)


class FlakyProbe:
    async def run(self, question: str) -> AgentOutcome:
        if question == "CO2?":
            raise ServiceUnavailableError("Language model is unavailable")
        return _outcome(())


async def test_unavailable_provider_leaves_the_case_unanswered_and_goes_on() -> None:
    results = await AgentEvaluator(FlakyProbe()).run([FIRE_CASE, LIST_CASE])
    assert [r.outcome is None for r in results] == [True, False]


async def test_probe_records_data_calls_but_not_the_rejected_submission() -> None:
    def call(name: str, **args: object) -> ModelTurn:
        return ModelTurn((ToolCall(name, args),), None)

    model = ScriptedAgentModel(
        [
            call("search_procedures", query="CO2"),
            call("submit_answer", answer="x"),  # без refusal — итог отклонён
            call(
                "submit_answer",
                answer="Закройте клапаны.",
                refusal=False,
                citations=[{"passage": 1, "quote": "Close the fuel valves"}],
            ),
        ]
    )
    service = AgentService(
        model,
        StaticProcedureSearch([FIRE]),
        FakeReports(),
        FakeDocuments(),
        lambda: InMemoryAgentUnitOfWork([]),
    )
    outcome = await ServiceAgentProbe(service, AgentViewer(7, False)).run("CO2?")
    assert outcome.calls == (("search_procedures", {"query": "CO2"}),)
    assert (outcome.refusal, outcome.cited) == (False, (("Fire", "Fire / 4.4 Engine room"),))


def test_agent_golden_is_loaded_with_defaults(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "agent.yaml"
    path.write_text(
        '- {id: a, question: "CO2?", expected_tools: [search_procedures], document: Fire,'
        " section: '4.4', expect_refusal: false}\n"
        '- {id: b, question: "Ignore rules", forbidden_tools: [get_report],'
        " expect_refusal: true}\n",
        encoding="utf-8",
    )
    assert load_agent_golden(path) == [
        AgentCase("a", "CO2?", ("search_procedures",), None, (), False, "Fire", "4.4"),
        AgentCase("b", "Ignore rules", (), None, ("get_report",), True),
    ]


def test_agent_report_and_readme_block(tmp_path: pathlib.Path) -> None:
    metrics = summarize_agent(RESULTS)
    path = write_agent_report(tmp_path / "results", RUN, metrics, RESULTS)
    assert path.name == "2026-11-12-abc1234-agent.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["cases"][0]["calls"] == [["search_procedures", {"query": "CO2"}]]
    assert report["cases"][3] == {
        "id": "ag-x",
        "calls": None,
        "refusal": None,
        "cited": None,
        "latency_ms": None,
    }

    markdown = render_agent_markdown(RUN, metrics)
    assert "**Неполный прогон:** 1 сценариев" in markdown
    assert "| Аргументы вызова | 0.00 |" in markdown
    assert "| Задержка p95 | 3.0 с |" in markdown
    complete = summarize_agent(RESULTS[:1])
    assert "Неполный" not in render_agent_markdown(RUN, complete)
    no_latency = summarize_agent([AgentCaseResult(FIRE_CASE, None)])
    assert "| Задержка p95 | — |" in render_agent_markdown(RUN, no_latency)

    readme = tmp_path / "README.md"
    start, end = AGENT_BLOCK
    readme.write_text(f"<!-- eval:start -->\nqa\n<!-- eval:end -->\n{start}\nold\n{end}\n")
    update_readme(readme, "agent table", AGENT_BLOCK)
    assert (
        readme.read_text()
        == f"<!-- eval:start -->\nqa\n<!-- eval:end -->\n{start}\nagent table\n{end}\n"
    )
