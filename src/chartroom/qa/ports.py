"""Что модулю qa нужно от внешнего мира."""

from typing import Protocol

from chartroom.qa.domain import Passage


class PassageRetriever(Protocol):
    async def retrieve(self, question: str, limit: int) -> list[Passage]:
        """Лучшие фрагменты актуальных процедур. Raises ServiceUnavailableError."""
        ...
