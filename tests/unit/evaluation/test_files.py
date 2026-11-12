import json
import pathlib
import subprocess
from datetime import date

import pytest

from chartroom.evaluation.adapters.files import (
    README_END,
    README_START,
    RunInfo,
    current_commit,
    load_golden,
    render_markdown,
    update_readme,
    write_report,
)
from chartroom.evaluation.domain import CaseKind, CaseResult, GoldenCase, Hit, Outcome, summarize

FIRE = GoldenCase("ru-01", "CO2?", CaseKind.ANSWERABLE, "Fire", "4.4")
BORSCH = GoldenCase("no-01", "Borsch?", CaseKind.UNANSWERABLE, None, None)
RESULTS = [
    CaseResult(
        FIRE,
        (Hit("Fire", "Fire / 4.4", 0.8),),
        Outcome(False, (("Fire", "Fire / 4.4"),), False, 4200),
    ),
    CaseResult(BORSCH, (Hit("Fire", "Fire / 1", 0.5),), None),
]


def _run(with_answers: bool = True) -> RunInfo:
    return RunInfo(
        date(2026, 11, 12), "abc1234", ("m1", "m2"), "answer.v2", "emb", 0.62, with_answers
    )


def test_golden_set_is_loaded_with_kinds(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "golden.yaml"
    path.write_text(
        '- {id: a, kind: answerable, question: "Q?", document: "Fire", section: "4.4"}\n'
        '- {id: b, kind: unanswerable, question: "Borsch?"}\n',
        encoding="utf-8",
    )
    assert load_golden(path) == [
        GoldenCase("a", "Q?", CaseKind.ANSWERABLE, "Fire", "4.4"),
        GoldenCase("b", "Borsch?", CaseKind.UNANSWERABLE, None, None),
    ]


def test_report_records_run_metrics_and_cases(tmp_path: pathlib.Path) -> None:
    path = write_report(tmp_path / "results", _run(), summarize(RESULTS, k=5), RESULTS)
    assert path.name == "2026-11-12-abc1234.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["run"]["generation_models"] == ["m1", "m2"]
    assert report["metrics"]["hit_at_k"] == 1.0
    assert [c["id"] for c in report["cases"]] == ["ru-01", "no-01"]
    assert (report["cases"][0]["rank"], report["cases"][1]["refusal"]) == (1, None)


def test_markdown_flags_incomplete_runs_and_unmeasured_values() -> None:
    markdown = render_markdown(_run(), summarize(RESULTS, k=5))
    assert "коммит `abc1234`" in markdown
    assert "ответы получены на 1 из 2" in markdown
    assert "**Неполный прогон:** 1 вопросов" in markdown
    assert "| hit@5 | 1.00 |" in markdown
    assert "| Точность отказов (вопросы без ответа) | — |" in markdown
    assert "| Задержка p50 / p95 | 4.2 / 4.2 с |" in markdown
    retrieval = render_markdown(_run(with_answers=False), summarize(RESULTS[:1], k=5))
    assert "только поиск, без генерации ответов" in retrieval
    assert "Неполный" not in retrieval


def test_readme_block_is_replaced_and_the_rest_kept(tmp_path: pathlib.Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text(f"# Title\n{README_START}\nold\n{README_END}\nfooter\n", encoding="utf-8")
    update_readme(readme, "new table")
    update_readme(readme, "newer table")
    assert (
        readme.read_text(encoding="utf-8")
        == f"# Title\n{README_START}\nnewer table\n{README_END}\nfooter\n"
    )


def test_readme_without_markers_is_an_error(tmp_path: pathlib.Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text("# Title\n", encoding="utf-8")
    with pytest.raises(ValueError):
        update_readme(readme, "table")


def test_commit_is_marked_dirty_and_unknown_outside_git(tmp_path: pathlib.Path) -> None:
    assert current_commit(tmp_path) == "unknown"

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init")
    clean = current_commit(tmp_path)
    (tmp_path / "file.txt").write_text("change")
    assert current_commit(tmp_path) == f"{clean}+dirty"
