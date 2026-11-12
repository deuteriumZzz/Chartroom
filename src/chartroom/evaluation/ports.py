"""Что модулю evaluation нужно от системы, которую он оценивает."""

from typing import Protocol

from chartroom.evaluation.domain import AgentOutcome, Hit, Outcome


class RetrievalProbe(Protocol):
    async def hits(self, question: str, limit: int) -> list[Hit]: ...


class AnswerProbe(Protocol):
    async def outcome(self, question: str) -> Outcome:
        """Raises ServiceUnavailableError, если ответ получить нельзя (лимит, перегрузка)."""
        ...


class AgentProbe(Protocol):
    async def run(self, question: str) -> AgentOutcome:
        """Raises ServiceUnavailableError, если агент не смог получить ответ модели."""
        ...
