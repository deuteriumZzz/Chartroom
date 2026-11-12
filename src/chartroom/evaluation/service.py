from collections.abc import Sequence

from chartroom.evaluation.domain import CaseResult, GoldenCase, Outcome
from chartroom.evaluation.ports import AnswerProbe, RetrievalProbe
from chartroom.shared.errors import ServiceUnavailableError

DEFAULT_K = 5


class Evaluator:
    """Прогон золотого набора: поиск для каждого вопроса и (по желанию) полный ответ."""

    def __init__(self, retrieval: RetrievalProbe, answers: AnswerProbe, k: int = DEFAULT_K) -> None:
        self._retrieval = retrieval
        self._answers = answers
        self.k = k

    async def run(self, cases: Sequence[GoldenCase], with_answers: bool) -> list[CaseResult]:
        results = []
        for case in cases:
            hits = tuple(await self._retrieval.hits(case.question, self.k))
            outcome: Outcome | None = None
            if with_answers:
                try:
                    outcome = await self._answers.outcome(case.question)
                except ServiceUnavailableError:
                    # Лимит или перегрузка провайдера: случай помечается невыполненным,
                    # метрики ответов считаются по выполненным, число невыполненных — в отчёте.
                    outcome = None
            results.append(CaseResult(case, hits, outcome))
        return results
