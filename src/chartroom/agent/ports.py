"""Что агенту нужно от внешнего мира: модель и данные других модулей (только чтение)."""

from collections.abc import Sequence
from typing import Any, Protocol, Self

from chartroom.agent.domain import AgentRun, AgentViewer, ModelTurn, Source, ToolResult
from chartroom.shared.language import Language


class AgentConversation(Protocol):
    @property
    def model(self) -> str | None:
        """Модель, которая ведёт диалог (известна после первого ответа)."""
        ...

    async def next_turn(self, results: Sequence[ToolResult]) -> ModelTurn:
        """Отдаёт модели результаты прошлых вызовов, возвращает её следующий ход."""
        ...


class AgentModel(Protocol):
    @property
    def prompt_version(self) -> str: ...

    def start(self, question: str, language: Language) -> AgentConversation: ...


class ProcedureSearch(Protocol):
    async def search(self, query: str, top_k: int) -> list[Source]:
        """Фрагменты процедур; поле number заполняет сервис агента."""
        ...


class ReportsReader(Protocol):
    async def list_reports(
        self, viewer: AgentViewer, status: str | None, template: str | None, limit: int
    ) -> list[dict[str, Any]]: ...

    async def get_report(self, viewer: AgentViewer, report_id: int) -> dict[str, Any]: ...

    async def get_template(self, name: str) -> dict[str, Any]: ...


class DocumentsReader(Protocol):
    async def active_version(self, title: str) -> dict[str, Any]: ...


class AgentRunLog(Protocol):
    async def add(self, run: AgentRun) -> int: ...


class AgentUnitOfWork(Protocol):
    @property
    def runs(self) -> AgentRunLog: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(self, *exc_info: object) -> None: ...

    async def commit(self) -> None: ...
