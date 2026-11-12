"""Золотой набор и метрики качества (FR-14, FR-15). Чистые функции — без I/O."""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from statistics import mean


class CaseKind(StrEnum):
    ANSWERABLE = "answerable"
    CROSS_LANGUAGE = "cross_language"  # ответ есть, но документ на другом языке
    UNANSWERABLE = "unanswerable"  # правильный результат — отказ


@dataclass(frozen=True, slots=True)
class GoldenCase:
    id: str
    question: str
    kind: CaseKind
    document: str | None  # точное название документа с ответом
    section: str | None  # часть пути раздела с ответом

    @property
    def expects_answer(self) -> bool:
        return self.kind is not CaseKind.UNANSWERABLE

    def matches(self, title: str, section_path: str) -> bool:
        return self.section is not None and title == self.document and self.section in section_path


@dataclass(frozen=True, slots=True)
class Hit:
    """Найденный фрагмент глазами eval: где он и насколько близок к вопросу."""

    title: str
    section_path: str
    similarity: float


@dataclass(frozen=True, slots=True)
class Outcome:
    """Итог ответа на вопрос: отказ, процитированные разделы, предупреждение, задержка."""

    refusal: bool
    cited: tuple[tuple[str, str], ...]  # (название документа, путь раздела)
    citation_warning: bool
    latency_ms: int


@dataclass(frozen=True, slots=True)
class CaseResult:
    case: GoldenCase
    hits: tuple[Hit, ...]
    outcome: Outcome | None  # None — ответ не получен (провайдер недоступен, лимит)

    @property
    def rank(self) -> int | None:
        return next(
            (
                n
                for n, hit in enumerate(self.hits, 1)
                if self.case.matches(hit.title, hit.section_path)
            ),
            None,
        )

    @property
    def best_similarity(self) -> float | None:
        return max((hit.similarity for hit in self.hits), default=None)


@dataclass(frozen=True, slots=True)
class Metrics:
    """None — метрику нечем посчитать (а не «ноль»): нет случаев нужного вида."""

    cases: int
    answered_cases: int
    k: int
    hit_at_k: float | None
    mrr: float | None
    refusal_accuracy: float | None  # доля отказов на вопросах без ответа
    false_refusal_rate: float | None  # доля отказов на вопросах с ответом
    citation_accuracy: float | None  # ответ процитировал ожидаемый раздел
    citation_warning_rate: float | None
    latency_p50_ms: int | None
    latency_p95_ms: int | None
    min_answerable_similarity: float | None
    max_unanswerable_similarity: float | None
    suggested_refusal_threshold: (
        float | None
    )  # середина зазора; None, если распределения пересекаются


def _share(flags: Sequence[bool]) -> float | None:
    return sum(flags) / len(flags) if flags else None


def percentile(values: Sequence[int], q: int) -> int:
    """Перцентиль методом nearest-rank: всегда одно из наблюдённых значений."""
    ordered = sorted(values)
    rank = max(1, math.ceil(q / 100 * len(ordered)))
    return ordered[rank - 1]


def summarize(results: Sequence[CaseResult], k: int) -> Metrics:
    with_answer = [r for r in results if r.case.expects_answer]
    ranks = [r.rank for r in with_answer]
    answered = [r for r in results if r.outcome is not None]
    answered_with = [r for r in answered if r.case.expects_answer]
    answered_without = [r for r in answered if not r.case.expects_answer]
    replied = [r for r in answered_with if r.outcome and not r.outcome.refusal]
    latencies = [r.outcome.latency_ms for r in answered if r.outcome]

    answerable_best = [s for r in with_answer if (s := r.best_similarity) is not None]
    unanswerable_best = [
        s for r in results if not r.case.expects_answer and (s := r.best_similarity) is not None
    ]
    low, high = min(answerable_best, default=None), max(unanswerable_best, default=None)
    threshold = (low + high) / 2 if low is not None and high is not None and high < low else None

    return Metrics(
        cases=len(results),
        answered_cases=len(answered),
        k=k,
        hit_at_k=_share([rank is not None and rank <= k for rank in ranks]),
        mrr=mean(1 / rank if rank else 0.0 for rank in ranks) if ranks else None,
        refusal_accuracy=_share([r.outcome.refusal for r in answered_without if r.outcome]),
        false_refusal_rate=_share([r.outcome.refusal for r in answered_with if r.outcome]),
        citation_accuracy=_share(
            [any(r.case.matches(*cited) for cited in r.outcome.cited) for r in replied if r.outcome]
        ),
        citation_warning_rate=_share([r.outcome.citation_warning for r in answered if r.outcome]),
        latency_p50_ms=percentile(latencies, 50) if latencies else None,
        latency_p95_ms=percentile(latencies, 95) if latencies else None,
        min_answerable_similarity=low,
        max_unanswerable_similarity=high,
        suggested_refusal_threshold=threshold,
    )
