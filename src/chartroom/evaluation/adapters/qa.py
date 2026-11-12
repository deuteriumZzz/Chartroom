"""Мост к модулю qa: eval задаёт вопросы той же системе, что видит пользователь."""

import time

from chartroom.evaluation.domain import Hit, Outcome
from chartroom.qa.ports import PassageRetriever
from chartroom.qa.service import QuestionService


class QaRetrievalProbe:
    def __init__(self, retriever: PassageRetriever) -> None:
        self._retriever = retriever

    async def hits(self, question: str, limit: int) -> list[Hit]:
        passages = await self._retriever.retrieve(question, limit)
        return [Hit(p.title, p.section_path, p.similarity) for p in passages]


class QaAnswerProbe:
    def __init__(self, questions: QuestionService, user_id: int) -> None:
        self._questions = questions
        self._user_id = user_id

    async def outcome(self, question: str) -> Outcome:
        started = time.perf_counter()
        answer = (await self._questions.ask(question, self._user_id)).answer
        return Outcome(
            refusal=answer.refusal,
            cited=tuple((c.title, c.section_path) for c in answer.citations),
            citation_warning=answer.citation_warning,
            latency_ms=round((time.perf_counter() - started) * 1000),
        )
