"""Шаблоны отчётов, извлечённые данные, статусы (FR-9…FR-12). Без фреймворков и I/O.

Схема шаблона и её проверка — общий валидатор `chartroom.shared.schema` (им же агент проверяет
аргументы инструментов).
"""

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from chartroom.shared.errors import ConflictError, InvalidInputError, NotFoundError
from chartroom.shared.schema import Issue, Schema

MAX_REPORT_TEXT = 10_000
_TEMPLATE_NAME = re.compile(r"^[a-z][a-z0-9_]{1,49}$")

ReportData = dict[str, Any]


class ReportStatus(StrEnum):
    DRAFT = "draft"  # замечаний нет, ждёт принятия
    NEEDS_REVIEW = "needs_review"  # есть замечания: поля пропущены или неверны
    ACCEPTED = "accepted"  # принят капитаном, больше не меняется


class InvalidTemplateNameError(InvalidInputError):
    message = "Template name must be 2-50 characters: lowercase letters, digits, underscore"


class InvalidReportTextError(InvalidInputError):
    message = f"Report text must be between 1 and {MAX_REPORT_TEXT} characters"


class TemplateNotFoundError(NotFoundError):
    message = "Report template not found"


class ReportNotFoundError(NotFoundError):
    # И для чужого отчёта тоже: по ответу нельзя узнать, что такой отчёт существует (IDOR).
    message = "Report not found"


class ReportLockedError(ConflictError):
    message = "Accepted report cannot be changed"


class ReportHasIssuesError(ConflictError):
    message = "Report with issues cannot be accepted"


class AcceptanceDeniedError(ConflictError):
    message = "Only a captain or admin can accept a report"


@dataclass(frozen=True, slots=True)
class ReportTemplate:
    id: int
    name: str
    title: str
    schema: Schema
    version: int


@dataclass(frozen=True, slots=True)
class Report:
    id: int
    template_id: int
    user_id: int
    source_text: str
    data: ReportData
    status: ReportStatus
    issues: tuple[Issue, ...]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Viewer:
    """Кто работает с отчётами. Роль переводит в это понятие HTTP-слой."""

    user_id: int
    is_supervisor: bool  # captain и admin: видят все отчёты и принимают их


def check_template_name(name: str) -> str:
    if not _TEMPLATE_NAME.fullmatch(name):
        raise InvalidTemplateNameError
    return name


def check_report_text(raw: str) -> str:
    text = raw.strip()
    if not text or len(text) > MAX_REPORT_TEXT:
        raise InvalidReportTextError
    return text


def status_for(issues: tuple[Issue, ...]) -> ReportStatus:
    return ReportStatus.NEEDS_REVIEW if issues else ReportStatus.DRAFT


def ensure_can_accept(report: Report, viewer: Viewer) -> None:
    if not viewer.is_supervisor:
        raise AcceptanceDeniedError
    if report.issues:
        raise ReportHasIssuesError
