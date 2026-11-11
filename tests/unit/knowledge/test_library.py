from datetime import date

import pytest

from chartroom.knowledge.domain.models import (
    MAX_UPLOAD_BYTES,
    DocumentNotFoundError,
    DocumentUpload,
    DuplicateFileError,
    DuplicateVersionError,
    FileTooLargeError,
    IndexingStatus,
    InvalidDocumentError,
    InvalidTitleError,
    InvalidVersionLabelError,
    Language,
)
from chartroom.knowledge.service import DocumentLibrary
from tests.fakes import InMemoryKnowledgeUnitOfWork, KnowledgeStore, RecordingQueue


def _upload(**changes: object) -> DocumentUpload:
    fields: dict[str, object] = {
        "title": "Fire Safety",
        "language": Language.EN,
        "label": "3",
        "issued_on": date(2026, 9, 1),
        "filename": "fire.md",
        "content": b"# Fire\n## 1. Purpose\nText.",
    }
    fields.update(changes)
    return DocumentUpload(**fields)  # type: ignore[arg-type]


@pytest.fixture
def store() -> KnowledgeStore:
    return KnowledgeStore()


@pytest.fixture
def queue() -> RecordingQueue:
    return RecordingQueue()


@pytest.fixture
def library(store: KnowledgeStore, queue: RecordingQueue) -> DocumentLibrary:
    return DocumentLibrary(lambda: InMemoryKnowledgeUnitOfWork(store), queue)


async def test_upload_saves_pending_version_and_enqueues_it(
    library: DocumentLibrary, store: KnowledgeStore, queue: RecordingQueue
) -> None:
    version = await library.upload(_upload(title="  Fire   Safety ", label=" 3 "))
    assert (version.label, version.status, version.is_active) == (
        "3",
        IndexingStatus.PENDING,
        False,
    )
    assert store.documents[version.document_id].title == "Fire Safety"
    assert store.contents[version.id] == _upload().content
    assert queue.enqueued == [version.id]


async def test_new_version_of_same_title_joins_the_document(library: DocumentLibrary) -> None:
    first = await library.upload(_upload())
    second = await library.upload(_upload(title="fire safety", label="4", content=b"# Fire v4"))
    assert second.document_id == first.document_id
    overview = await library.overview(first.document_id)
    assert [v.label for v in overview.versions] == ["3", "4"]


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"label": "3", "content": b"# other"}, DuplicateVersionError),
        ({"label": "4"}, DuplicateFileError),
    ],
)
async def test_duplicate_upload_is_rejected_and_not_enqueued(
    library: DocumentLibrary,
    queue: RecordingQueue,
    changes: dict[str, object],
    error: type[Exception],
) -> None:
    await library.upload(_upload())
    with pytest.raises(error):
        await library.upload(_upload(**changes))
    assert len(queue.enqueued) == 1


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"content": b"x" * (MAX_UPLOAD_BYTES + 1)}, FileTooLargeError),
        ({"filename": "fire.pdf"}, InvalidDocumentError),
        ({"title": "   "}, InvalidTitleError),
        ({"label": " "}, InvalidVersionLabelError),
    ],
)
async def test_invalid_upload_stores_nothing(
    library: DocumentLibrary,
    store: KnowledgeStore,
    queue: RecordingQueue,
    changes: dict[str, object],
    error: type[Exception],
) -> None:
    with pytest.raises(error):
        await library.upload(_upload(**changes))
    assert (store.versions, queue.enqueued) == ({}, [])


async def test_overview_of_missing_document(library: DocumentLibrary) -> None:
    with pytest.raises(DocumentNotFoundError):
        await library.overview(404)
