"""Файлы eval: золотой набор (YAML), отчёт (JSON) и таблица метрик в README."""

import json
import pathlib
import subprocess
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date

import yaml

from chartroom.evaluation.domain import (
    AgentCase,
    AgentCaseResult,
    AgentMetrics,
    CaseKind,
    CaseResult,
    GoldenCase,
    Metrics,
)

README_START = "<!-- eval:start -->"
README_END = "<!-- eval:end -->"
AGENT_BLOCK = ("<!-- agent-eval:start -->", "<!-- agent-eval:end -->")


@dataclass(frozen=True, slots=True)
class RunInfo:
    """С чем именно получены цифры: без этого метрики нельзя ни повторить, ни сравнить."""

    date: date
    commit: str
    generation_models: tuple[str, ...]
    prompt_version: str
    embedding_model: str
    refusal_threshold: float
    with_answers: bool


def load_golden(path: pathlib.Path) -> list[GoldenCase]:
    cases = []
    for item in yaml.safe_load(path.read_text(encoding="utf-8")):
        kind = CaseKind(item["kind"])
        expects = kind is not CaseKind.UNANSWERABLE
        cases.append(
            GoldenCase(
                id=item["id"],
                question=item["question"],
                kind=kind,
                document=item["document"] if expects else None,
                section=item["section"] if expects else None,
            )
        )
    return cases


def current_commit(cwd: pathlib.Path) -> str:
    """Короткий хеш HEAD; «+dirty», если в рабочем дереве есть незакоммиченные изменения."""

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
        ).stdout.strip()

    try:
        sha = git("rev-parse", "--short", "HEAD")
        return f"{sha}+dirty" if git("status", "--porcelain") else sha
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def write_report(
    results_dir: pathlib.Path, run: RunInfo, metrics: Metrics, results: Sequence[CaseResult]
) -> pathlib.Path:
    results_dir.mkdir(parents=True, exist_ok=True)
    path = results_dir / f"{run.date.isoformat()}-{run.commit}.json"
    cases = [
        {
            "id": r.case.id,
            "kind": r.case.kind,
            "rank": r.rank,
            "best_similarity": r.best_similarity,
            "refusal": r.outcome.refusal if r.outcome else None,
            "cited": [list(c) for c in r.outcome.cited] if r.outcome else None,
            "citation_warning": r.outcome.citation_warning if r.outcome else None,
            "latency_ms": r.outcome.latency_ms if r.outcome else None,
        }
        for r in results
    ]
    report = {
        "run": asdict(run) | {"date": run.date.isoformat()},
        "metrics": asdict(metrics),
        "cases": cases,
    }
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _value(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}"


def render_markdown(run: RunInfo, metrics: Metrics) -> str:
    skipped = metrics.cases - metrics.answered_cases
    answers = (
        f"ответы получены на {metrics.answered_cases} из {metrics.cases}"
        if run.with_answers
        else "только поиск, без генерации ответов"
    )
    latency = (
        f"{metrics.latency_p50_ms / 1000:.1f} / {metrics.latency_p95_ms / 1000:.1f} с"
        if metrics.latency_p50_ms is not None and metrics.latency_p95_ms is not None
        else "—"
    )
    lines = [
        f"Прогон {run.date.isoformat()}, коммит `{run.commit}`: "
        f"{metrics.cases} вопросов, {answers}.",
        f"Модели генерации: {', '.join(run.generation_models)}; промпт `{run.prompt_version}`; "
        f"эмбеддинги `{run.embedding_model}`; порог отказа {run.refusal_threshold:.2f}.",
    ]
    if run.with_answers and skipped:
        lines.append(
            f"**Неполный прогон:** {skipped} вопросов без ответа провайдера (лимит или перегрузка)."
        )
    lines += [
        "",
        "| Метрика | Значение |",
        "|---|---|",
        f"| hit@{metrics.k} | {_value(metrics.hit_at_k)} |",
        f"| MRR | {_value(metrics.mrr)} |",
        f"| Точность отказов (вопросы без ответа) | {_value(metrics.refusal_accuracy)} |",
        f"| Ложные отказы (вопросы с ответом) | {_value(metrics.false_refusal_rate)} |",
        f"| Корректность цитат | {_value(metrics.citation_accuracy)} |",
        f"| Доля ответов с `citation_warning` | {_value(metrics.citation_warning_rate)} |",
        f"| Задержка p50 / p95 | {latency} |",
        f"| Сходство: мин. у вопросов с ответом / макс. у вопросов без | "
        f"{_value(metrics.min_answerable_similarity)} / "
        f"{_value(metrics.max_unanswerable_similarity)} |",
    ]
    return "\n".join(lines)


def update_readme(
    readme: pathlib.Path, markdown: str, markers: tuple[str, str] = (README_START, README_END)
) -> None:
    opening, closing = markers
    text = readme.read_text(encoding="utf-8")
    start, end = text.find(opening), text.find(closing)
    if start < 0 or end < start:
        raise ValueError(f"{readme} has no {opening} … {closing} block")
    head, tail = text[: start + len(opening)], text[end:]
    readme.write_text(f"{head}\n{markdown}\n{tail}", encoding="utf-8")


def load_agent_golden(path: pathlib.Path) -> list[AgentCase]:
    return [
        AgentCase(
            id=item["id"],
            question=item["question"],
            expected_tools=tuple(item.get("expected_tools", ())),
            expected_args=item.get("expected_args"),
            forbidden_tools=tuple(item.get("forbidden_tools", ())),
            expect_refusal=item.get("expect_refusal"),
            document=item.get("document"),
            section=item.get("section"),
        )
        for item in yaml.safe_load(path.read_text(encoding="utf-8"))
    ]


def write_agent_report(
    results_dir: pathlib.Path,
    run: RunInfo,
    metrics: AgentMetrics,
    results: Sequence[AgentCaseResult],
) -> pathlib.Path:
    results_dir.mkdir(parents=True, exist_ok=True)
    path = results_dir / f"{run.date.isoformat()}-{run.commit}-agent.json"
    cases = [
        {
            "id": r.case.id,
            "calls": [[name, dict(args)] for name, args in r.outcome.calls] if r.outcome else None,
            "refusal": r.outcome.refusal if r.outcome else None,
            "cited": [list(c) for c in r.outcome.cited] if r.outcome else None,
            "latency_ms": r.outcome.latency_ms if r.outcome else None,
        }
        for r in results
    ]
    report = {
        "run": asdict(run) | {"date": run.date.isoformat()},
        "metrics": asdict(metrics),
        "cases": cases,
    }
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def render_agent_markdown(run: RunInfo, metrics: AgentMetrics) -> str:
    skipped = metrics.cases - metrics.answered_cases
    lines = [
        f"Прогон {run.date.isoformat()}, коммит `{run.commit}`: {metrics.cases} сценариев, "
        f"выполнено {metrics.answered_cases}; модели {', '.join(run.generation_models)}, "
        f"промпт `{run.prompt_version}`.",
    ]
    if skipped:
        lines.append(f"**Неполный прогон:** {skipped} сценариев без ответа провайдера.")
    p95 = "—" if metrics.latency_p95_ms is None else f"{metrics.latency_p95_ms / 1000:.1f} с"
    lines += [
        "",
        "| Метрика агента | Значение |",
        "|---|---|",
        f"| Выбор инструмента | {_value(metrics.tool_selection_accuracy)} |",
        f"| Аргументы вызова | {_value(metrics.argument_accuracy)} |",
        f"| Вызовы запрещённых инструментов | {_value(metrics.forbidden_call_rate)} |",
        f"| Точность отказов (в т.ч. prompt injection) | {_value(metrics.refusal_accuracy)} |",
        f"| Корректность цитат | {_value(metrics.citation_accuracy)} |",
        f"| Задержка p95 | {p95} |",
    ]
    return "\n".join(lines)
