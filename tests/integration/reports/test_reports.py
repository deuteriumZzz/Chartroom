import asyncio
import json
import pathlib
from collections.abc import AsyncIterator, Callable

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from chartroom import cli
from chartroom.bootstrap import Container, build_container
from chartroom.identity.adapters.persistence import SqlIdentityUnitOfWork
from chartroom.identity.domain import Role
from chartroom.main import create_app
from chartroom.reports.adapters.persistence import (
    ReportTemplateRecord,
    SqlReportsUnitOfWork,
    TemplateVersionConflictError,
)
from chartroom.reports.domain import Issue, ReportStatus
from chartroom.reports.ports import ReportsUnitOfWork
from chartroom.shared.config import Settings, get_settings
from tests.fakes import InMemoryReportsUnitOfWork, RecordingQueue, ReportsStore, ScriptedExtractor

SCHEMA = {
    "type": "object",
    "properties": {"crew_total": {"type": "integer"}, "crew_present": {"type": "integer"}},
    "required": ["crew_total", "crew_present"],
}
PASSWORD = "s3cret-pass"


@pytest.fixture(params=["in-memory", "sql"])
async def uow_and_user(
    request: pytest.FixtureRequest, session_factory: async_sessionmaker[AsyncSession]
) -> tuple[Callable[[], ReportsUnitOfWork], int]:
    if request.param == "in-memory":
        store = ReportsStore()
        return (lambda: InMemoryReportsUnitOfWork(store)), 1
    async with SqlIdentityUnitOfWork(session_factory) as identity:
        user = await identity.users.add("r@ship.test", "h", Role.OFFICER)
        await identity.commit()
    return (lambda: SqlReportsUnitOfWork(session_factory)), user.id


async def test_storage_contract(uow_and_user: tuple[Callable[[], ReportsUnitOfWork], int]) -> None:
    uow_factory, user_id = uow_and_user
    async with uow_factory() as uow:
        v1 = await uow.templates.add("drill", "Drill", SCHEMA)
        v2 = await uow.templates.add("drill", "Drill v2", SCHEMA)
        await uow.templates.add("noon", "Noon", SCHEMA)
        report = await uow.reports.add(
            v2.id,
            user_id,
            "text",
            {"crew_total": 22},
            ReportStatus.NEEDS_REVIEW,
            (Issue("crew_present", "required"),),
        )
        await uow.commit()
    async with uow_factory() as uow:
        assert (v1.version, v2.version) == (1, 2)
        assert await uow.templates.latest("drill") == v2
        assert await uow.templates.get(v1.id) == v1
        assert [(t.name, t.version) for t in await uow.templates.list_latest()] == [
            ("drill", 2),
            ("noon", 1),
        ]
        assert await uow.templates.latest("missing") is None
        stored = await uow.reports.get(report.id)
        assert stored is not None and (stored.data, stored.issues) == (
            {"crew_total": 22},
            (Issue("crew_present", "required"),),
        )
        updated = await uow.reports.update(
            report.id, {"crew_total": 22, "crew_present": 22}, ReportStatus.DRAFT, ()
        )
        await uow.commit()
    async with uow_factory() as uow:
        assert await uow.reports.get(report.id) == updated
        assert await uow.reports.get(report.id + 1000) is None


@pytest.fixture
async def http(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[tuple[AsyncClient, Container]]:
    container = build_container(
        get_settings(),
        session_factory,
        RecordingQueue(),
        extractor=ScriptedExtractor({"crew_total": 22, "crew_present": None}),
    )
    async with AsyncClient(
        transport=ASGITransport(app=create_app(container)), base_url="http://test"
    ) as client:
        yield client, container


async def _login(http: tuple[AsyncClient, Container], role: Role, name: str) -> dict[str, str]:
    client, container = http
    await container.identity.register(f"{name}@ship.test", PASSWORD, role)
    r = await client.post(
        "/auth/login", data={"username": f"{name}@ship.test", "password": PASSWORD}
    )
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_report_flow_over_http(http: tuple[AsyncClient, Container]) -> None:
    client, _ = http
    admin = await _login(http, Role.ADMIN, "admin")
    officer = await _login(http, Role.OFFICER, "officer")
    captain = await _login(http, Role.CAPTAIN, "captain")
    stranger = await _login(http, Role.OFFICER, "stranger")

    created = await client.post(
        "/report-templates",
        headers=admin,
        json={"name": "drill", "title": "Drill", "schema": SCHEMA},
    )
    assert (created.status_code, created.json()["version"], created.json()["schema"]) == (
        201,
        1,
        SCHEMA,
    )
    assert (
        await client.post(
            "/report-templates", headers=officer, json={"name": "x", "title": "X", "schema": SCHEMA}
        )
    ).status_code == 403
    assert [t["name"] for t in (await client.get("/report-templates", headers=officer)).json()] == [
        "drill"
    ]

    extracted = await client.post(
        "/reports/extract", headers=officer, json={"template": "drill", "text": "Drill, 22 crew"}
    )
    report = extracted.json()
    assert (extracted.status_code, report["status"], report["issues"]) == (
        201,
        "needs_review",
        [{"field": "crew_present", "message": "required"}],
    )
    path = f"/reports/{report['id']}"

    assert (await client.get(path, headers=stranger)).status_code == 404
    fixed = (await client.patch(path, headers=officer, json={"data": {"crew_present": 22}})).json()
    assert (fixed["status"], fixed["issues"]) == ("draft", [])
    assert (await client.patch(path, headers=officer, json={"accept": True})).status_code == 409
    assert (await client.patch(path, headers=captain, json={"accept": True})).json()[
        "status"
    ] == "accepted"
    locked = await client.patch(path, headers=captain, json={"data": {"crew_present": 1}})
    assert (locked.status_code, locked.json()) == (
        409,
        {"detail": "Accepted report cannot be changed"},
    )


@pytest.mark.parametrize(
    ("body", "status"),
    [({"template": "drill", "text": ""}, 422), ({"template": "nope", "text": "x"}, 404)],
)
async def test_bad_extract_requests(
    http: tuple[AsyncClient, Container], body: dict[str, str], status: int
) -> None:
    officer = await _login(http, Role.OFFICER, "officer")
    assert (
        await http[0].post("/reports/extract", headers=officer, json=body)
    ).status_code == status


@pytest.mark.usefixtures("engine")
def test_seed_templates_creates_once(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: pathlib.Path
) -> None:
    def container_without_queue(settings: Settings) -> Container:
        return build_container(settings, queue=RecordingQueue())

    monkeypatch.setattr(cli, "build_container", container_without_queue)
    (tmp_path / "seed_test.json").write_text(
        json.dumps({"name": "seed_test", "title": "Seed", "schema": SCHEMA}), encoding="utf-8"
    )
    cli.main(["seed-templates", "--dir", str(tmp_path)])
    cli.main(["seed-templates", "--dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert (
        "created  seed_test  (version 1)" in out and "skipped  seed_test  (already exists)" in out
    )


async def test_concurrent_template_versions_conflict_instead_of_failing(
    engine: AsyncEngine,
) -> None:
    """Две транзакции одновременно сохраняют версию 1 шаблона: вторая получает 409, а не 500."""
    first = SqlReportsUnitOfWork(async_sessionmaker(engine, expire_on_commit=False))
    second = SqlReportsUnitOfWork(async_sessionmaker(engine, expire_on_commit=False))
    try:
        async with first as a, second as b:
            await a.templates.add("race_test", "A", SCHEMA)  # держит блокировку уникального индекса
            pending = asyncio.create_task(b.templates.add("race_test", "B", SCHEMA))
            await asyncio.sleep(0.2)  # вторая вставка ждёт решения первой транзакции
            await a.commit()
            with pytest.raises(TemplateVersionConflictError):
                await pending
    finally:
        async with engine.begin() as conn:
            await conn.execute(
                delete(ReportTemplateRecord).where(ReportTemplateRecord.name == "race_test")
            )
