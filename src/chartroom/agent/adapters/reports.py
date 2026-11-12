"""Мост к модулю reports. Права проверяет ReportService: агент передаёт пользователя из токена."""

from typing import Any

from chartroom.agent.domain import AgentViewer
from chartroom.reports.domain import Report, ReportStatus, TemplateNotFoundError, Viewer
from chartroom.reports.service import ReportService


def _viewer(viewer: AgentViewer) -> Viewer:
    return Viewer(viewer.user_id, is_supervisor=viewer.is_supervisor)


def _summary(report: Report, names: dict[int, str]) -> dict[str, Any]:
    return {
        "report_id": report.id,
        "template": names.get(report.template_id),
        "status": report.status.value,
        "issues": len(report.issues),
        "created_at": report.created_at.isoformat(),
    }


class ReportServiceReader:
    def __init__(self, reports: ReportService) -> None:
        self._reports = reports

    async def list_reports(
        self, viewer: AgentViewer, status: str | None, template: str | None, limit: int
    ) -> list[dict[str, Any]]:
        found = await self._reports.list_for(
            _viewer(viewer), ReportStatus(status) if status else None, template, limit
        )
        names = {t.id: t.name for t in await self._reports.templates()}
        return [_summary(report, names) for report in found]

    async def get_report(self, viewer: AgentViewer, report_id: int) -> dict[str, Any]:
        report = await self._reports.get(report_id, _viewer(viewer))
        names = {t.id: t.name for t in await self._reports.templates()}
        return _summary(report, names) | {
            "data": report.data,
            "issues": [{"field": i.field, "message": i.message} for i in report.issues],
        }

    async def get_template(self, name: str) -> dict[str, Any]:
        template = next((t for t in await self._reports.templates() if t.name == name), None)
        if template is None:
            raise TemplateNotFoundError
        properties = template.schema["properties"]
        return {
            "name": template.name,
            "title": template.title,
            "version": template.version,
            "fields": {field: spec.get("title", field) for field, spec in properties.items()},
            "required": template.schema.get("required", []),
        }
