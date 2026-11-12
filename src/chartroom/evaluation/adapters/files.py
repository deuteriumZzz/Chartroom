"""Файлы eval: золотой набор (YAML), отчёт (JSON) и таблица метрик в README."""

import json
import pathlib
import subprocess
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date

import yaml

from chartroom.evaluation.domain import CaseKind, CaseResult, GoldenCase, Metrics

README_START = "<!-- eval:start -->"
README_END = "<!-- eval:end -->"


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


def update_readme(readme: pathlib.Path, markdown: str) -> None:
    text = readme.read_text(encoding="utf-8")
    start, end = text.find(README_START), text.find(README_END)
    if start < 0 or end < start:
        raise ValueError(f"{readme} has no {README_START} … {README_END} block")
    head, tail = text[: start + len(README_START)], text[end:]
    readme.write_text(f"{head}\n{markdown}\n{tail}", encoding="utf-8")
