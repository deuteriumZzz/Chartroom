from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from chartroom.bootstrap import Container, build_container
from chartroom.identity.domain import Role
from chartroom.knowledge.domain.models import MAX_UPLOAD_BYTES
from chartroom.main import create_app
from chartroom.shared.config import get_settings
from chartroom.shared.errors import ServiceUnavailableError
from tests.fakes import RecordingQueue

PASSWORD = "s3cret-pass"
FIRE = b"# Fire\n## 1. Purpose\nDefines actions."
FORM = {"title": "Fire Safety", "version": "3", "language": "en", "issued_on": "2026-09-01"}


class DownQueue:
    async def enqueue(self, version_id: int) -> None:
        raise ServiceUnavailableError("Indexing queue is unavailable")


@pytest.fixture
def queue() -> RecordingQueue:
    return RecordingQueue()


@pytest.fixture
def container(
    session_factory: async_sessionmaker[AsyncSession], queue: RecordingQueue
) -> Container:
    return build_container(get_settings(), session_factory, queue=queue)


async def _client(container: Container) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=create_app(container)), base_url="http://test")


@pytest.fixture
async def client(container: Container) -> AsyncIterator[AsyncClient]:
    async with await _client(container) as c:
        yield c


async def _headers(client: AsyncClient, container: Container, role: Role) -> dict[str, str]:
    email = f"{role}@ship.test"
    await container.identity.register(email, PASSWORD, role)
    r = await client.post("/auth/login", data={"username": email, "password": PASSWORD})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _upload(
    client: AsyncClient,
    headers: dict[str, str],
    filename: str = "fire.md",
    content: bytes = FIRE,
    **form: str,
) -> tuple[int, dict[str, object]]:
    r = await client.post(
        "/documents", headers=headers, data=FORM | form, files={"file": (filename, content)}
    )
    return r.status_code, r.json()


async def test_admin_uploads_and_sees_pending_status(
    client: AsyncClient, container: Container, queue: RecordingQueue
) -> None:
    admin = await _headers(client, container, Role.ADMIN)
    status, body = await _upload(client, admin, filename="../../etc/fire.md")
    assert status == 202
    version = body["version"]
    assert isinstance(version, dict)
    assert (version["status"], version["is_active"], version["filename"]) == (
        "pending",
        False,
        "fire.md",
    )
    assert queue.enqueued == [version["id"]]

    r = await client.get(f"/documents/{body['document_id']}/status", headers=admin)
    assert r.status_code == 200
    assert (r.json()["title"], [v["label"] for v in r.json()["versions"]]) == ("Fire Safety", ["3"])


async def test_only_admin_manages_documents(client: AsyncClient, container: Container) -> None:
    officer = await _headers(client, container, Role.OFFICER)
    assert (await _upload(client, officer))[0] == 403
    assert (await _upload(client, {}))[0] == 401
    assert (await client.get("/documents/1/status", headers=officer)).status_code == 403


@pytest.mark.parametrize(
    ("filename", "content", "form", "expected"),
    [
        ("fire.md", FIRE, {}, (409, "This version label already exists for the document")),
        (
            "fire.pdf",
            b"# not a pdf",
            {"version": "4"},
            (422, "File is corrupted or does not match its format"),
        ),
        (
            "fire.md",
            b"x" * (MAX_UPLOAD_BYTES + 1),
            {"version": "4"},
            (422, "File is larger than 20 MB"),
        ),
        ("setup.exe", b"MZ", {"version": "4"}, (422, "Supported formats: pdf, docx, md, txt")),
    ],
)
async def test_bad_uploads_are_rejected_with_clear_reason(
    client: AsyncClient,
    container: Container,
    filename: str,
    content: bytes,
    form: dict[str, str],
    expected: tuple[int, str],
) -> None:
    admin = await _headers(client, container, Role.ADMIN)
    await _upload(client, admin)
    status, body = await _upload(client, admin, filename, content, **form)
    assert (status, body["detail"]) == expected


async def test_status_of_missing_document_is_404(client: AsyncClient, container: Container) -> None:
    admin = await _headers(client, container, Role.ADMIN)
    r = await client.get("/documents/999/status", headers=admin)
    assert (r.status_code, r.json()) == (404, {"detail": "Document not found"})


async def test_queue_outage_is_503_with_retry_after(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    container = build_container(get_settings(), session_factory, queue=DownQueue())
    async with await _client(container) as client:
        admin = await _headers(client, container, Role.ADMIN)
        r = await client.post(
            "/documents", headers=admin, data=FORM, files={"file": ("fire.md", FIRE)}
        )
    assert (r.status_code, r.json(), r.headers["Retry-After"]) == (
        503,
        {"detail": "Indexing queue is unavailable"},
        "30",
    )
