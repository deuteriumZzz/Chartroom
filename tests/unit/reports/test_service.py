import pytest

from chartroom.reports.domain import (
    AcceptanceDeniedError,
    InvalidReportTextError,
    InvalidTemplateNameError,
    ReportHasIssuesError,
    ReportLockedError,
    ReportNotFoundError,
    ReportStatus,
    TemplateNotFoundError,
    Viewer,
)
from chartroom.reports.service import ReportService
from chartroom.shared.schema import InvalidTemplateError, Issue
from tests.fakes import InMemoryReportsUnitOfWork, ReportsStore, ScriptedExtractor

SCHEMA = {
    "type": "object",
    "properties": {
        "crew_total": {"type": "integer", "minimum": 1},
        "crew_present": {"type": "integer", "minimum": 0},
        "remarks": {"type": "string"},
    },
    "required": ["crew_total", "crew_present"],
    "x-lte": [["crew_present", "crew_total"]],
}
OFFICER, OTHER = Viewer(7, is_supervisor=False), Viewer(8, is_supervisor=False)
CAPTAIN = Viewer(1, is_supervisor=True)


async def _service(extracted: dict[str, object]) -> tuple[ReportService, ScriptedExtractor]:
    extractor = ScriptedExtractor(extracted)
    service = ReportService(lambda: InMemoryReportsUnitOfWork(ReportsStore()), extractor)
    store = ReportsStore()
    service = ReportService(lambda: InMemoryReportsUnitOfWork(store), extractor)
    await service.create_template("drill_checklist", "Drill", SCHEMA)
    return service, extractor


async def test_new_template_name_gets_next_version_and_list_shows_latest() -> None:
    service, _ = await _service({})
    second = await service.create_template("drill_checklist", "  Drill v2 ", SCHEMA)
    await service.create_template("noon_report", "Noon", SCHEMA)
    assert (second.version, second.title) == (2, "Drill v2")
    assert [(t.name, t.version) for t in await service.templates()] == [
        ("drill_checklist", 2),
        ("noon_report", 1),
    ]


@pytest.mark.parametrize(
    ("name", "title", "schema", "error"),
    [
        ("Drill List", "T", SCHEMA, InvalidTemplateNameError),
        ("ok_name", "  ", SCHEMA, InvalidTemplateError),
        ("ok_name", "T", {"type": "array"}, InvalidTemplateError),
    ],
)
async def test_invalid_templates_are_rejected(
    name: str, title: str, schema: dict[str, object], error: type[Exception]
) -> None:
    service, _ = await _service({})
    with pytest.raises(error):
        await service.create_template(name, title, schema)


async def test_extracted_report_with_gaps_needs_review() -> None:
    service, extractor = await _service({"crew_total": 22, "crew_present": None, "remarks": None})
    report = await service.extract(
        "drill_checklist", "  Fire drill, 22 crew on board. ", OFFICER.user_id
    )
    assert extractor.calls == [("Fire drill, 22 crew on board.", "drill_checklist")]
    assert (report.status, report.issues, report.user_id) == (
        ReportStatus.NEEDS_REVIEW,
        (Issue("crew_present", "required"),),
        OFFICER.user_id,
    )


async def test_complete_report_is_a_draft() -> None:
    service, _ = await _service({"crew_total": 22, "crew_present": 21})
    report = await service.extract("drill_checklist", "text", OFFICER.user_id)
    assert (report.status, report.issues) == (ReportStatus.DRAFT, ())


async def test_fixing_a_field_clears_the_issue_and_captain_accepts() -> None:
    service, _ = await _service({"crew_total": 22, "crew_present": None})
    report = await service.extract("drill_checklist", "text", OFFICER.user_id)
    fixed = await service.update(report.id, OFFICER, {"crew_present": 22}, accept=False)
    assert (fixed.status, fixed.issues, fixed.data["crew_present"]) == (ReportStatus.DRAFT, (), 22)
    accepted = await service.update(report.id, CAPTAIN, {}, accept=True)
    assert accepted.status is ReportStatus.ACCEPTED
    with pytest.raises(ReportLockedError):
        await service.update(report.id, CAPTAIN, {"remarks": "late"}, accept=False)


async def test_acceptance_rules() -> None:
    service, _ = await _service({"crew_total": 22, "crew_present": 30})
    report = await service.extract("drill_checklist", "text", OFFICER.user_id)
    with pytest.raises(AcceptanceDeniedError):
        await service.update(report.id, OFFICER, {"crew_present": 20}, accept=True)
    with pytest.raises(ReportHasIssuesError):
        await service.update(report.id, CAPTAIN, {}, accept=True)
    still = await service.get(report.id, OFFICER)
    assert still.status is ReportStatus.NEEDS_REVIEW  # отказ в принятии ничего не меняет


async def test_someone_elses_report_looks_missing_but_captain_sees_it() -> None:
    service, _ = await _service({"crew_total": 22, "crew_present": 22})
    report = await service.extract("drill_checklist", "text", OFFICER.user_id)
    assert (await service.get(report.id, CAPTAIN)).id == report.id
    for call in (
        service.get(report.id, OTHER),
        service.update(report.id, OTHER, {}, accept=False),
        service.get(999, CAPTAIN),
    ):
        with pytest.raises(ReportNotFoundError):
            await call


@pytest.mark.parametrize(
    ("template", "text", "error"),
    [
        ("missing", "text", TemplateNotFoundError),
        ("drill_checklist", "   ", InvalidReportTextError),
    ],
)
async def test_extract_input_errors(template: str, text: str, error: type[Exception]) -> None:
    service, extractor = await _service({})
    with pytest.raises(error):
        await service.extract(template, text, OFFICER.user_id)
    assert extractor.calls == []


async def test_listing_respects_ownership_and_filters() -> None:
    service, extractor = await _service({"crew_total": 22, "crew_present": 22})
    await service.create_template("noon_report", "Noon", SCHEMA)
    mine = await service.extract("drill_checklist", "text", OFFICER.user_id)
    extractor.data = {"crew_total": 22, "crew_present": None}
    theirs = await service.extract("noon_report", "text", OTHER.user_id)
    assert [r.id for r in await service.list_for(OFFICER)] == [mine.id]
    assert [r.id for r in await service.list_for(CAPTAIN)] == [theirs.id, mine.id]
    assert [r.id for r in await service.list_for(CAPTAIN, status=ReportStatus.NEEDS_REVIEW)] == [
        theirs.id
    ]
    assert [r.id for r in await service.list_for(CAPTAIN, template_name="drill_checklist")] == [
        mine.id
    ]
    assert len(await service.list_for(CAPTAIN, limit=1)) == 1
