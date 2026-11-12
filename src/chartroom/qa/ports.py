"""Что модулю qa нужно от внешнего мира."""

from collections.abc import Sequence
from typing import Protocol, Self

from chartroom.qa.domain import (
    AnswerLanguage,
    Feedback,
    GeneratedAnswer,
    LoggedQuery,
    Passage,
    QueryEntry,
)


class PassageRetriever(Protocol):
    async def retrieve(self, question: str, limit: int) -> list[Passage]:
        """Лучшие фрагменты актуальных процедур. Raises ServiceUnavailableError."""
        ...


class AnswerGenerator(Protocol):
    @property
    def prompt_version(self) -> str: ...

    async def generate(
        self, question: str, language: AnswerLanguage, passages: Sequence[Passage]
    ) -> GeneratedAnswer:
        """Ответ только по переданным фрагментам. Raises ServiceUnavailableError."""
        ...


class QueryLog(Protocol):
    async def add(self, entry: QueryEntry) -> int: ...

    async def get(self, query_id: int) -> LoggedQuery | None: ...

    async def list(self, user_id: int | None, limit: int, offset: int) -> list[LoggedQuery]:
        """Новые сначала. user_id=None — запросы всех пользователей."""
        ...


class FeedbackRepository(Protocol):
    async def save(self, query_id: int, feedback: Feedback) -> None:
        """Повторный отзыв на тот же запрос заменяет прежний."""
        ...


class QaUnitOfWork(Protocol):
    @property
    def queries(self) -> QueryLog: ...

    @property
    def feedback(self) -> FeedbackRepository: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(self, *exc_info: object) -> None: ...

    async def commit(self) -> None: ...
