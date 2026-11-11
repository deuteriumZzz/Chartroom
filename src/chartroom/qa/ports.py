"""Что модулю qa нужно от внешнего мира."""

from collections.abc import Sequence
from typing import Protocol

from chartroom.qa.domain import AnswerLanguage, GeneratedAnswer, Passage


class PassageRetriever(Protocol):
    async def retrieve(self, question: str, limit: int) -> list[Passage]:
        """Лучшие фрагменты актуальных процедур. Raises ServiceUnavailableError."""
        ...


class AnswerGenerator(Protocol):
    async def generate(
        self, question: str, language: AnswerLanguage, passages: Sequence[Passage]
    ) -> GeneratedAnswer:
        """Ответ только по переданным фрагментам. Raises ServiceUnavailableError."""
        ...
