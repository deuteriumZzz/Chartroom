"""Стартовые шаблоны (FR-13): корректная схема и проверка, которая ловит типичные ошибки."""

import json
import pathlib

import pytest

from chartroom.reports.domain import Issue, check_schema, validate

TEMPLATES = sorted(
    (pathlib.Path(__file__).resolve().parents[3] / "data" / "templates").glob("*.json")
)


def _schema(name: str) -> dict[str, object]:
    spec = json.loads(next(p for p in TEMPLATES if p.stem == name).read_text(encoding="utf-8"))
    schema: dict[str, object] = spec["schema"]
    return schema


def test_three_starter_templates_with_supported_schemas() -> None:
    assert [p.stem for p in TEMPLATES] == ["drill_checklist", "mooring_operation", "noon_report"]
    for path in TEMPLATES:
        spec = json.loads(path.read_text(encoding="utf-8"))
        assert spec["name"] == path.stem and "подтвердить автором" in spec["title"]
        check_schema(spec["schema"])


@pytest.mark.parametrize(
    ("template", "data", "expected"),
    [
        (
            "noon_report",
            {
                "report_date": "2026-11-12",
                "latitude": 54.7,
                "longitude": 20.5,
                "speed_knots": 12.5,
                "distance_nm": 300,
                "rob_hfo_t": -5,
                "rob_mgo_t": 40,
            },
            [Issue("rob_hfo_t", "must be at least 0")],
        ),
        (
            "drill_checklist",
            {
                "drill_date": "2026-11-12",
                "drill_type": "fire",
                "crew_total": 20,
                "crew_present": 22,
                "equipment_tested": True,
            },
            [Issue("crew_present", "must not exceed crew_total")],
        ),
        (
            "mooring_operation",
            {
                "operation_date": "2026-11-12",
                "port": "Kaliningrad",
                "first_line_time": "14:40",
                "all_fast_time": "14:10",
                "lines_forward": 4,
                "lines_aft": 4,
                "injuries": False,
            },
            [Issue("first_line_time", "must not exceed all_fast_time")],
        ),
    ],
)
def test_templates_catch_typical_mistakes(
    template: str, data: dict[str, object], expected: list[Issue]
) -> None:
    assert list(validate(_schema(template), data)) == expected
