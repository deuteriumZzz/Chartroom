import asyncio
import json
import pathlib

import pytest

from chartroom import cli
from chartroom.agent.domain import ModelTurn, ToolCall
from chartroom.bootstrap import Container, build_container
from chartroom.identity.domain import Role
from chartroom.qa.domain import GeneratedAnswer, Passage, RawCitation
from chartroom.shared.config import Settings, get_settings
from tests.fakes import (
    RecordingQueue,
    ScriptedAgentModel,
    ScriptedGenerator,
    StaticPassageRetriever,
)

PASSAGE = Passage(
    1, 7, "Fire", "Fire / 4.4 Engine room", None, "Close the fuel valves.", 0.03, 0.81
)
ANSWER = GeneratedAnswer(
    "Close the valves.", (RawCitation(1, "Close the fuel valves"),), False, "m"
)


@pytest.mark.usefixtures("engine")  # БД с применёнными миграциями
async def test_eval_writes_report_and_readme(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_search(settings: Settings) -> Container:
        return build_container(
            settings,
            queue=RecordingQueue(),
            retriever=StaticPassageRetriever([PASSAGE]),
            generator=ScriptedGenerator(ANSWER),
        )

    setup = build_container(get_settings(), queue=RecordingQueue())
    await setup.identity.register("eval-cli@ship.test", "s3cret-pass", Role.ADMIN)
    await setup.aclose()
    monkeypatch.setattr(cli, "build_container", fake_search)

    golden = tmp_path / "golden.yaml"
    golden.write_text(
        '- {id: ru-01, kind: answerable, question: "CO2?", document: "Fire",'
        ' section: "4.4 Engine room"}\n'
        '- {id: no-01, kind: unanswerable, question: "Borsch?"}\n',
        encoding="utf-8",
    )
    readme = tmp_path / "README.md"
    readme.write_text("# R\n<!-- eval:start -->\n<!-- eval:end -->\n", encoding="utf-8")
    args = [
        "eval",
        "--as",
        "eval-cli@ship.test",
        "--golden",
        str(golden),
        "--results-dir",
        str(tmp_path / "results"),
        "--readme",
        str(readme),
    ]

    await asyncio.to_thread(cli.main, args)  # CLI сам запускает свой event loop

    [report] = list((tmp_path / "results").glob("*.json"))
    metrics = json.loads(report.read_text(encoding="utf-8"))["metrics"]
    assert (metrics["cases"], metrics["answered_cases"], metrics["hit_at_k"]) == (2, 2, 1.0)
    assert "| hit@5 | 1.00 |" in readme.read_text(encoding="utf-8")


def test_eval_for_unknown_user_is_a_clear_error(tmp_path: pathlib.Path) -> None:
    with pytest.raises(SystemExit, match="error: User not found"):
        cli.main(
            [
                "eval",
                "--as",
                "ghost@ship.test",
                "--golden",
                "eval/golden.yaml",
                "--readme",
                str(tmp_path / "R.md"),
            ]
        )


@pytest.mark.usefixtures("engine")
async def test_agent_eval_runs_as_the_given_user_and_writes_its_block(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = ScriptedAgentModel(
        [ModelTurn((ToolCall("list_reports", {"status": "needs_review"}),), None)]
    )

    def fake_agent(settings: Settings) -> Container:
        return build_container(settings, queue=RecordingQueue(), agent_model=model)

    setup = build_container(get_settings(), queue=RecordingQueue())
    await setup.identity.register("agent-cli@ship.test", "s3cret-pass", Role.OFFICER)
    await setup.aclose()
    monkeypatch.setattr(cli, "build_container", fake_agent)

    golden = tmp_path / "agent.yaml"
    golden.write_text(
        '- {id: ag-03, question: "Мои отчёты?", expected_tools: [list_reports],'
        " expected_args: {status: needs_review}}\n",
        encoding="utf-8",
    )
    readme = tmp_path / "README.md"
    readme.write_text("<!-- agent-eval:start -->\n<!-- agent-eval:end -->\n", encoding="utf-8")
    args = ["eval", "--agent", "--as", "agent-cli@ship.test", "--golden", str(golden)]
    args += ["--results-dir", str(tmp_path / "results"), "--readme", str(readme)]

    await asyncio.to_thread(cli.main, args)

    [report] = list((tmp_path / "results").glob("*-agent.json"))
    metrics = json.loads(report.read_text(encoding="utf-8"))["metrics"]
    assert (metrics["tool_selection_accuracy"], metrics["argument_accuracy"]) == (1.0, 1.0)
    assert "| Выбор инструмента | 1.00 |" in readme.read_text(encoding="utf-8")
