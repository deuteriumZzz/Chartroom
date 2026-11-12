from datetime import UTC, datetime
from typing import Any, Self

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, UniqueConstraint, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from chartroom.reports.domain import (
    Issue,
    Report,
    ReportData,
    ReportStatus,
    ReportTemplate,
    Schema,
)
from chartroom.shared.database import Base, SqlAlchemyUnitOfWork
from chartroom.shared.errors import ConflictError


class TemplateVersionConflictError(ConflictError):
    message = "Template was changed concurrently, retry"


def _now() -> datetime:
    return datetime.now(UTC)


class ReportTemplateRecord(Base):
    __tablename__ = "report_templates"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_report_templates_name_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(200))
    schema: Mapped[dict[str, Any]] = mapped_column(JSONB)
    version: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    def to_domain(self) -> ReportTemplate:
        return ReportTemplate(self.id, self.name, self.title, self.schema, self.version)


class ReportRecord(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("report_templates.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    source_text: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[ReportStatus] = mapped_column(
        Enum(
            ReportStatus,
            name="report_status",
            native_enum=False,
            create_constraint=True,
            length=16,
            values_callable=lambda members: [m.value for m in members],
        )
    )
    # Замечания пересчитываются целиком при каждой правке, поэтому хранятся одним полем (ADR-011).
    issues: Mapped[list[dict[str, str]]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    def to_domain(self) -> Report:
        return Report(
            id=self.id,
            template_id=self.template_id,
            user_id=self.user_id,
            source_text=self.source_text,
            data=self.data,
            status=self.status,
            issues=tuple(Issue(i["field"], i["message"]) for i in self.issues),
            created_at=self.created_at,
        )


def _issues(issues: tuple[Issue, ...]) -> list[dict[str, str]]:
    return [{"field": i.field, "message": i.message} for i in issues]


class SqlTemplateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, template_id: int) -> ReportTemplate:
        return (await self._session.get_one(ReportTemplateRecord, template_id)).to_domain()

    async def latest(self, name: str) -> ReportTemplate | None:
        record = await self._session.scalar(
            select(ReportTemplateRecord)
            .where(ReportTemplateRecord.name == name)
            .order_by(ReportTemplateRecord.version.desc())
            .limit(1)
        )
        return record.to_domain() if record else None

    async def list_latest(self) -> list[ReportTemplate]:
        newest = (
            select(
                ReportTemplateRecord.name, func.max(ReportTemplateRecord.version).label("version")
            )
            .group_by(ReportTemplateRecord.name)
            .subquery()
        )
        records = await self._session.scalars(
            select(ReportTemplateRecord)
            .join(
                newest,
                (ReportTemplateRecord.name == newest.c.name)
                & (ReportTemplateRecord.version == newest.c.version),
            )
            .order_by(ReportTemplateRecord.name)
        )
        return [record.to_domain() for record in records]

    async def add(self, name: str, title: str, schema: Schema) -> ReportTemplate:
        current = await self.latest(name)
        record = ReportTemplateRecord(
            name=name, title=title, schema=schema, version=(current.version if current else 0) + 1
        )
        self._session.add(record)
        try:
            await self._session.flush()
        except IntegrityError as e:  # две одновременные правки одного шаблона
            raise TemplateVersionConflictError from e
        return record.to_domain()


class SqlReportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, report_id: int) -> Report | None:
        record = await self._session.get(ReportRecord, report_id)
        return record.to_domain() if record else None

    async def add(
        self,
        template_id: int,
        user_id: int,
        source_text: str,
        data: ReportData,
        status: ReportStatus,
        issues: tuple[Issue, ...],
    ) -> Report:
        record = ReportRecord(
            template_id=template_id,
            user_id=user_id,
            source_text=source_text,
            data=data,
            status=status,
            issues=_issues(issues),
        )
        self._session.add(record)
        await self._session.flush()
        return record.to_domain()

    async def update(
        self, report_id: int, data: ReportData, status: ReportStatus, issues: tuple[Issue, ...]
    ) -> Report:
        record = await self._session.get_one(ReportRecord, report_id)
        record.data, record.status, record.issues = data, status, _issues(issues)
        await self._session.flush()
        return record.to_domain()


class SqlReportsUnitOfWork(SqlAlchemyUnitOfWork):
    templates: SqlTemplateRepository
    reports: SqlReportRepository

    async def __aenter__(self) -> Self:
        await super().__aenter__()
        self.templates = SqlTemplateRepository(self.session)
        self.reports = SqlReportRepository(self.session)
        return self
