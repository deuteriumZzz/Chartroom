"""Что модулю evaluation нужно от системы, которую он оценивает."""

from typing import Protocol

from chartroom.evaluation.domain import Hit, Outcome


class RetrievalProbe(Protocol):
    async def hits(self, question: str, limit: int) -> list[Hit]: ...


class AnswerProbe(Protocol):
    async def outcome(self, question: str) -> Outcome:
        """Raises ServiceUnavailableError, если ответ получить нельзя (лимит, перегрузка)."""
        ...
