import pytest

from chartroom.shared.schema import InvalidTemplateError, Issue, check_schema, validate

DRILL = {
    "type": "object",
    "properties": {
        "drill_date": {"type": "string", "format": "date", "title": "Дата"},
        "drill_type": {"type": "string", "enum": ["fire", "abandon_ship"]},
        "start_time": {"type": "string", "format": "time"},
        "muster_minutes": {"type": "number", "minimum": 0, "maximum": 30},
        "crew_total": {"type": "integer", "minimum": 1},
        "crew_present": {"type": "integer", "minimum": 0},
        "equipment_tested": {"type": "boolean"},
        "remarks": {"type": "string"},
    },
    "required": ["drill_date", "drill_type", "crew_total", "crew_present"],
    "x-lte": [["crew_present", "crew_total"]],
}
GOOD = {
    "drill_date": "2026-11-10",
    "drill_type": "fire",
    "start_time": "10:30",
    "muster_minutes": 4.5,
    "crew_total": 22,
    "crew_present": 22,
    "equipment_tested": True,
    "remarks": None,
}


def test_complete_consistent_report_has_no_issues() -> None:
    assert validate(DRILL, GOOD) == ()


def test_missing_required_fields_are_reported() -> None:
    issues = validate(DRILL, GOOD | {"drill_date": None, "crew_total": "  "})
    assert issues == (Issue("drill_date", "required"), Issue("crew_total", "required"))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("muster_minutes", "five", "must be a number"),
        (
            "muster_minutes",
            True,
            "must be a number",
        ),  # bool — не число, хоть Python и считает иначе
        ("crew_total", 21.5, "must be an integer"),
        ("equipment_tested", "yes", "must be true or false"),
        ("remarks", 42, "must be a string"),
        ("muster_minutes", -1, "must be at least 0"),
        ("muster_minutes", 31, "must be at most 30"),
        ("drill_type", "party", "must be one of: fire, abandon_ship"),
        ("drill_date", "10.11.2026", "must be a date (YYYY-MM-DD)"),
        ("drill_date", "2026-02-30", "must be a date (YYYY-MM-DD)"),
        ("start_time", "25:00", "must be a time (HH:MM)"),
    ],
)
def test_type_range_enum_and_format_violations(field: str, value: object, message: str) -> None:
    assert validate(DRILL, GOOD | {field: value}) == (Issue(field, message),)


def test_cross_field_consistency() -> None:
    assert validate(DRILL, GOOD | {"crew_present": 23}) == (
        Issue("crew_present", "must not exceed crew_total"),
    )
    # Пропущенное поле не даёт второго, ложного замечания о согласованности.
    assert validate(DRILL, GOOD | {"crew_present": None}) == (Issue("crew_present", "required"),)


def test_integer_written_as_whole_float_is_accepted() -> None:
    assert validate(DRILL, GOOD | {"crew_total": 22.0}) == ()


def test_unknown_fields_from_the_model_are_reported() -> None:
    assert validate(DRILL, GOOD | {"captain_mood": "good"}) == (
        Issue("captain_mood", "unknown field"),
    )


def test_supported_schema_passes_the_check() -> None:
    check_schema(DRILL)


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "array"},
        {"type": "object", "properties": {}},
        {"type": "object", "properties": {"a": {"type": "array"}}},
        {"type": "object", "properties": {"a": {"type": "string", "pattern": "x"}}},
        {"type": "object", "properties": {"a": {"type": "string", "format": "email"}}},
        {"type": "object", "properties": {"a": {"type": "string", "minimum": 1}}},
        {"type": "object", "properties": {"a": {"type": "number"}}, "required": ["b"]},
        {"type": "object", "properties": {"a": {"type": "number"}}, "x-lte": [["a", "b"]]},
        {"type": "object", "properties": {"a": {"type": "string", "enum": []}}},
        {"type": "object", "properties": {"a": {"type": "number"}}, "oneOf": []},
    ],
)
def test_unsupported_schema_is_rejected_not_ignored(schema: dict[str, object]) -> None:
    with pytest.raises(InvalidTemplateError):
        check_schema(schema)
