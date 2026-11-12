from collections.abc import Callable
from dataclasses import replace

from chartroom.reports.domain import (
    InvalidTemplateError,
    Report,
    ReportData,
    ReportLockedError,
    ReportNotFoundError,
    ReportStatus,
    ReportTemplate,
    Schema,
    TemplateNotFoundError,
    Viewer,
    check_report_text,
    check_schema,
    check_template_name,
    ensure_can_accept,
    status_for,
    validate,
)
from chartroom.reports.ports import ReportExtractor, ReportsUnitOfWork

UowFactory = Callable[[], ReportsUnitOfWork]


class ReportService:
    """Отчёты и чек-листы: шаблоны, извлечение из текста, проверка, правка, принятие."""

    def __init__(self, uow_factory: UowFactory, extractor: ReportExtractor) -> None:
        self._uow_factory = uow_factory
        self._extractor = extractor

    async def create_template(self, name: str, title: str, schema: Schema) -> ReportTemplate:
        check_template_name(name)
        check_schema(schema)
        if not title.strip():
            raise InvalidTemplateError
        async with self._uow_factory() as uow:
            template = await uow.templates.add(name, title.strip(), schema)
            await uow.commit()
        return template

    async def templates(self) -> list[ReportTemplate]:
        async with self._uow_factory() as uow:
            return await uow.templates.list_latest()

    async def extract(self, template_name: str, text: str, user_id: int) -> Report:
        text = check_report_text(text)
        async with self._uow_factory() as uow:
            template = await uow.templates.latest(template_name)
        if template is None:
            raise TemplateNotFoundError
        data = await self._extractor.extract(text, template)
        issues = validate(template.schema, data)
        async with self._uow_factory() as uow:
            report = await uow.reports.add(
                template.id, user_id, text, data, status_for(issues), issues
            )
            await uow.commit()
        return report

    async def get(self, report_id: int, viewer: Viewer) -> Report:
        async with self._uow_factory() as uow:
            return await self._visible(uow, report_id, viewer)

    async def update(
        self, report_id: int, viewer: Viewer, changes: ReportData, accept: bool
    ) -> Report:
        """Правка полей (поверх извлечённых) и, по желанию, принятие отчёта.

        Замечания пересчитываются заново: исправленное поле перестаёт быть замечанием.
        """
        async with self._uow_factory() as uow:
            report = await self._visible(uow, report_id, viewer)
            if report.status is ReportStatus.ACCEPTED:
                raise ReportLockedError
            template = await uow.templates.get(report.template_id)
            data = report.data | changes
            issues = validate(template.schema, data)
            status = status_for(issues)
            if accept:
                ensure_can_accept(replace(report, issues=issues), viewer)
                status = ReportStatus.ACCEPTED
            updated = await uow.reports.update(report_id, data, status, issues)
            await uow.commit()
        return updated

    @staticmethod
    async def _visible(uow: ReportsUnitOfWork, report_id: int, viewer: Viewer) -> Report:
        report = await uow.reports.get(report_id)
        # Чужой отчёт неотличим от несуществующего (IDOR); руководитель видит все.
        if report is None or (report.user_id != viewer.user_id and not viewer.is_supervisor):
            raise ReportNotFoundError
        return report
