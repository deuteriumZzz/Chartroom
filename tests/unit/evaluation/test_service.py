from chartroom.evaluation.domain import CaseKind, GoldenCase, Hit, Outcome
from chartroom.evaluation.service import Evaluator
from chartroom.shared.errors import ServiceUnavailableError

CASES = [
    GoldenCase("ru-01", "CO2?", CaseKind.ANSWERABLE, "Fire", "4.4"),
    GoldenCase("no-01", "Borsch?", CaseKind.UNANSWERABLE, None, None),
]
HIT = Hit("Fire", "Fire / 4.4", 0.8)


class Probes:
    def __init__(self, unavailable: frozenset[str] = frozenset()) -> None:
        self.asked: list[str] = []
        self.searched: list[tuple[str, int]] = []
        self._unavailable = unavailable

    async def hits(self, question: str, limit: int) -> list[Hit]:
        self.searched.append((question, limit))
        return [HIT]

    async def outcome(self, question: str) -> Outcome:
        self.asked.append(question)
        if question in self._unavailable:
            raise ServiceUnavailableError("Language model is unavailable")
        return Outcome(False, (("Fire", "Fire / 4.4"),), False, 1200)


async def test_every_case_is_searched_and_answered() -> None:
    probes = Probes()
    results = await Evaluator(probes, probes, k=3).run(CASES, with_answers=True)
    assert [(r.case.id, r.hits, r.outcome is not None) for r in results] == [
        ("ru-01", (HIT,), True),
        ("no-01", (HIT,), True),
    ]
    assert probes.searched == [("CO2?", 3), ("Borsch?", 3)]


async def test_unavailable_provider_marks_case_not_completed_and_goes_on() -> None:
    probes = Probes(unavailable=frozenset({"CO2?"}))
    results = await Evaluator(probes, probes).run(CASES, with_answers=True)
    assert [r.outcome is None for r in results] == [True, False]


async def test_retrieval_only_run_never_calls_the_model() -> None:
    probes = Probes()
    results = await Evaluator(probes, probes).run(CASES, with_answers=False)
    assert probes.asked == [] and all(r.outcome is None for r in results)
