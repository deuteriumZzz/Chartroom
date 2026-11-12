import pytest

from chartroom.evaluation.domain import (
    CaseKind,
    CaseResult,
    GoldenCase,
    Hit,
    Outcome,
    percentile,
    summarize,
)

FIRE = GoldenCase("ru-01", "CO2?", CaseKind.ANSWERABLE, "Fire", "4.4 Engine room")
ALARM = GoldenCase("x-01", "Alarm?", CaseKind.CROSS_LANGUAGE, "Abandon", "4.1 Alarm")
BORSCH = GoldenCase("no-01", "Borsch?", CaseKind.UNANSWERABLE, None, None)

ENGINE = Hit("Fire", "Fire / 4. Actions / 4.4 Engine room", 0.81)
SCOPE = Hit("Fire", "Fire / 2. Scope", 0.70)
GALLEY = Hit("Fire", "Fire / 1. Purpose", 0.52)


def _outcome(
    refusal: bool, cited: tuple[Hit, ...] = (), warning: bool = False, ms: int = 1000
) -> Outcome:
    return Outcome(refusal, tuple((h.title, h.section_path) for h in cited), warning, ms)


def test_case_matches_by_document_and_section_part() -> None:
    assert FIRE.matches("Fire", "Fire / 4. Actions / 4.4 Engine room")
    assert not FIRE.matches("Other", "Fire / 4. Actions / 4.4 Engine room")
    assert not FIRE.matches("Fire", "Fire / 2. Scope")
    assert not BORSCH.matches("Fire", "Fire / 2. Scope")


def test_rank_is_position_of_first_expected_hit() -> None:
    assert CaseResult(FIRE, (SCOPE, ENGINE), None).rank == 2
    assert CaseResult(FIRE, (SCOPE,), None).rank is None


def test_retrieval_metrics_count_only_cases_with_an_answer() -> None:
    results = [
        CaseResult(FIRE, (ENGINE, SCOPE), None),  # ранг 1
        CaseResult(ALARM, (SCOPE, GALLEY, ENGINE), None),  # ожидаемого раздела нет → промах
        CaseResult(BORSCH, (GALLEY,), None),  # без ответа: в hit@k не входит
    ]
    metrics = summarize(results, k=5)
    assert (metrics.hit_at_k, metrics.mrr) == (0.5, 0.5)
    assert (metrics.cases, metrics.answered_cases) == (3, 0)


def test_answer_metrics_use_completed_cases_only() -> None:
    results = [
        CaseResult(FIRE, (ENGINE,), _outcome(False, (ENGINE,), ms=900)),  # ответ, верная цитата
        CaseResult(
            ALARM, (ENGINE,), _outcome(False, (SCOPE,), warning=True, ms=3000)
        ),  # цитата мимо
        CaseResult(FIRE, (ENGINE,), _outcome(True, ms=200)),  # ложный отказ
        CaseResult(BORSCH, (GALLEY,), _outcome(True, ms=100)),  # верный отказ
        CaseResult(BORSCH, (GALLEY,), None),  # провайдер недоступен — не учитывается
    ]
    metrics = summarize(results, k=5)
    assert (metrics.cases, metrics.answered_cases) == (5, 4)
    assert metrics.refusal_accuracy == 1.0
    assert metrics.false_refusal_rate == pytest.approx(1 / 3)
    assert metrics.citation_accuracy == 0.5  # из двух ответов верный раздел процитирован в одном
    assert metrics.citation_warning_rate == 0.25
    assert (metrics.latency_p50_ms, metrics.latency_p95_ms) == (200, 3000)


def test_similarity_gap_shows_where_the_refusal_threshold_can_sit() -> None:
    results = [
        CaseResult(FIRE, (ENGINE, SCOPE), None),
        CaseResult(ALARM, (SCOPE,), None),
        CaseResult(BORSCH, (GALLEY,), None),
    ]
    metrics = summarize(results, k=5)
    assert (metrics.min_answerable_similarity, metrics.max_unanswerable_similarity) == (0.70, 0.52)
    assert metrics.suggested_refusal_threshold == pytest.approx(0.61)


def test_overlapping_similarities_give_no_threshold() -> None:
    overlapping = CaseResult(BORSCH, (Hit("Fire", "Fire / 1", 0.9),), None)
    metrics = summarize([CaseResult(ALARM, (SCOPE,), None), overlapping], k=5)
    assert metrics.suggested_refusal_threshold is None


def test_metrics_without_data_are_none_not_zero() -> None:
    metrics = summarize([CaseResult(BORSCH, (), None)], k=5)
    assert (metrics.hit_at_k, metrics.refusal_accuracy, metrics.latency_p95_ms) == (
        None,
        None,
        None,
    )


@pytest.mark.parametrize(("q", "expected"), [(50, 3), (95, 5), (100, 5), (0, 1)])
def test_percentile_is_nearest_rank(q: int, expected: int) -> None:
    assert percentile([5, 1, 4, 2, 3], q) == expected
