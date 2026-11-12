"""Проверка данных по JSON Schema из небольшого явного подмножества.

Поддерживается: типы string/number/integer/boolean, minimum/maximum, enum, format date/time,
required и расширение x-lte («поле A не больше поля B») для согласованности полей. Схема с
чем-то другим отклоняется: наполовину применённое правило опаснее явной ошибки (ADR-011).
Используется шаблонами отчётов и аргументами инструментов агента.
"""

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from chartroom.shared.errors import InvalidInputError

Schema = dict[str, Any]

_TYPES = {"string", "number", "integer", "boolean"}
_SCHEMA_KEYS = {"type", "properties", "required", "x-lte", "title", "description"}
_FIELD_KEYS = {"type", "title", "description", "minimum", "maximum", "enum", "format"}
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class InvalidTemplateError(InvalidInputError):
    message = "Template schema uses unsupported JSON Schema features"


@dataclass(frozen=True, slots=True)
class Issue:
    field: str
    message: str


def check_schema(schema: Schema) -> None:
    properties = schema.get("properties")
    if schema.get("type") != "object" or set(schema) - _SCHEMA_KEYS:
        raise InvalidTemplateError
    if not isinstance(properties, dict) or not properties:
        raise InvalidTemplateError
    for spec in properties.values():
        if not isinstance(spec, dict) or spec.get("type") not in _TYPES or set(spec) - _FIELD_KEYS:
            raise InvalidTemplateError
        numeric = spec["type"] in ("number", "integer")
        if not numeric and ("minimum" in spec or "maximum" in spec):
            raise InvalidTemplateError
        formatted = "format" in spec
        if formatted and (spec["type"] != "string" or spec["format"] not in ("date", "time")):
            raise InvalidTemplateError
        if "enum" in spec and (not isinstance(spec["enum"], list) or not spec["enum"]):
            raise InvalidTemplateError
    if any(name not in properties for name in schema.get("required", [])):
        raise InvalidTemplateError
    for pair in schema.get("x-lte", []):
        if len(pair) != 2 or any(name not in properties for name in pair):
            raise InvalidTemplateError


def _missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _is_date(value: str) -> bool:
    if not _DATE.fullmatch(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _problem(spec: Schema, value: Any) -> str | None:
    kind = spec["type"]
    if kind == "string":
        if not isinstance(value, str):
            return "must be a string"
        if spec.get("format") == "date" and not _is_date(value):
            return "must be a date (YYYY-MM-DD)"
        if spec.get("format") == "time" and not _TIME.fullmatch(value):
            return "must be a time (HH:MM)"
    elif kind == "boolean":
        if not isinstance(value, bool):
            return "must be true or false"
    else:  # number, integer; bool в Python — подкласс int, но числом не считается
        if isinstance(value, bool) or not isinstance(value, int | float):
            return "must be a number" if kind == "number" else "must be an integer"
        if kind == "integer" and value != int(value):
            return "must be an integer"
        if "minimum" in spec and value < spec["minimum"]:
            return f"must be at least {spec['minimum']:g}"
        if "maximum" in spec and value > spec["maximum"]:
            return f"must be at most {spec['maximum']:g}"
    if "enum" in spec and value not in spec["enum"]:
        return "must be one of: " + ", ".join(map(str, spec["enum"]))
    return None


def validate(schema: Schema, data: dict[str, Any]) -> tuple[Issue, ...]:
    """FR-11: обязательные поля, типы, форматы, enum, диапазоны и согласованность полей."""
    properties: Schema = schema["properties"]
    required = set(schema.get("required", []))
    issues: list[Issue] = []
    for name, spec in properties.items():
        value = data.get(name)
        if _missing(value):
            if name in required:
                issues.append(Issue(name, "required"))
            continue
        problem = _problem(spec, value)
        if problem:
            issues.append(Issue(name, problem))
    flagged = {issue.field for issue in issues}
    for left, right in schema.get("x-lte", []):
        # Только корректно заполненные поля: иначе к «required» добавилась бы ложная ошибка.
        if _missing(data.get(left)) or _missing(data.get(right)) or {left, right} & flagged:
            continue
        if data[left] > data[right]:
            issues.append(Issue(left, f"must not exceed {right}"))
    issues += [Issue(name, "unknown field") for name in data if name not in properties]
    return tuple(issues)
