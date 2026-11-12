"""Что модулю reports нужно от внешнего мира."""

from typing import Protocol, Self

from chartroom.reports.domain import (
    Report,
    ReportData,
    ReportStatus,
    ReportTemplate,
)
from chartroom.shared.schema import Issue, Schema


class TemplateRepository(Protocol):
    async def get(self, template_id: int) -> ReportTemplate:
        """Шаблон отчёта существует всегда: внешний ключ не даёт удалить шаблон с отчётами."""
        ...

    async def latest(self, name: str) -> ReportTemplate | None: ...

    async def list_latest(self) -> list[ReportTemplate]:
        """Последняя версия каждого шаблона, по имени."""
        ...

    async def add(self, name: str, title: str, schema: Schema) -> ReportTemplate:
        """Новая версия шаблона: номер на единицу больше последнего."""
        ...


class ReportRepository(Protocol):
    async def get(self, report_id: int) -> Report | None: ...

    async def add(
        self,
        template_id: int,
        user_id: int,
        source_text: str,
        data: ReportData,
        status: ReportStatus,
        issues: tuple[Issue, ...],
    ) -> Report: ...

    async def update(
        self, report_id: int, data: ReportData, status: ReportStatus, issues: tuple[Issue, ...]
    ) -> Report: ...

    async def list(
        self,
        user_id: int | None,
        status: ReportStatus | None,
        template_name: str | None,
        limit: int,
    ) -> list[Report]:
        """Новые сначала. user_id=None — отчёты всех пользователей."""
        ...


class ReportsUnitOfWork(Protocol):
    @property
    def templates(self) -> TemplateRepository: ...

    @property
    def reports(self) -> ReportRepository: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(self, *exc_info: object) -> None: ...

    async def commit(self) -> None: ...


class ReportExtractor(Protocol):
    async def extract(self, text: str, template: ReportTemplate) -> ReportData:
        """Поля шаблона из свободного текста; неизвестное — None. Raises ServiceUnavailableError."""
        ...
