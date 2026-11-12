"""HTTP-адаптер модуля reports: шаблоны, извлечение, проверка и статусы (FR-9…FR-12)."""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, ConfigDict, Field

from chartroom.identity.api import AdminUser, OfficerUser
from chartroom.identity.domain import Role, User
from chartroom.reports.domain import MAX_REPORT_TEXT, Report, ReportStatus, ReportTemplate, Viewer
from chartroom.reports.service import ReportService

router = APIRouter(tags=["reports"])


def get_reports(request: Request) -> ReportService:
    reports: ReportService = request.app.state.container.reports
    return reports


ReportsDep = Annotated[ReportService, Depends(get_reports)]


def _viewer(user: User) -> Viewer:
    # Роль переводится в понятие reports здесь, на краю модуля: ядро о ролях не знает.
    return Viewer(user.id, is_supervisor=user.role.is_at_least(Role.CAPTAIN))


class TemplateRequest(BaseModel):
    name: str
    title: str = Field(min_length=1, max_length=200)
    schema_: dict[str, Any] = Field(alias="schema")


class TemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    name: str
    title: str
    version: int
    schema_: dict[str, Any] = Field(serialization_alias="schema")

    @classmethod
    def of(cls, template: ReportTemplate) -> "TemplateResponse":
        return cls(
            id=template.id,
            name=template.name,
            title=template.title,
            version=template.version,
            schema_=template.schema,
        )


class ExtractRequest(BaseModel):
    template: str
    text: str = Field(min_length=1, max_length=MAX_REPORT_TEXT)


class IssueResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    field: str
    message: str


class ReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    template_id: int
    user_id: int
    status: ReportStatus
    data: dict[str, Any]
    issues: list[IssueResponse]
    source_text: str
    created_at: datetime

    @classmethod
    def of(cls, report: Report) -> "ReportResponse":
        return cls.model_validate(report)


class ReportPatch(BaseModel):
    data: dict[str, Any] = Field(default_factory=dict)
    accept: bool = False


@router.post("/report-templates", status_code=status.HTTP_201_CREATED, response_model_by_alias=True)
async def create_template(
    request: TemplateRequest, _: AdminUser, reports: ReportsDep
) -> TemplateResponse:
    """Новый шаблон или новая версия существующего (то же имя). Отчёты ссылаются на версию."""
    template = await reports.create_template(request.name, request.title, request.schema_)
    return TemplateResponse.of(template)


@router.get("/report-templates", response_model_by_alias=True)
async def list_templates(_: OfficerUser, reports: ReportsDep) -> list[TemplateResponse]:
    return [TemplateResponse.of(t) for t in await reports.templates()]


@router.post("/reports/extract", status_code=status.HTTP_201_CREATED)
async def extract_report(
    request: ExtractRequest, user: OfficerUser, reports: ReportsDep
) -> ReportResponse:
    """Заполняет шаблон по свободному тексту и сразу проверяет: data + issues[]."""
    return ReportResponse.of(await reports.extract(request.template, request.text, user.id))


@router.get("/reports/{report_id}")
async def get_report(report_id: int, user: OfficerUser, reports: ReportsDep) -> ReportResponse:
    return ReportResponse.of(await reports.get(report_id, _viewer(user)))


@router.patch("/reports/{report_id}")
async def update_report(
    report_id: int, patch: ReportPatch, user: OfficerUser, reports: ReportsDep
) -> ReportResponse:
    """Исправить поля и/или принять отчёт (captain и admin, только без замечаний)."""
    report = await reports.update(report_id, _viewer(user), patch.data, patch.accept)
    return ReportResponse.of(report)
