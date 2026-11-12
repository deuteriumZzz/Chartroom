from datetime import date

import pytest

from chartroom.bootstrap import build_document_chunker
from chartroom.knowledge.domain.indexing import chunk_point_id
from chartroom.knowledge.domain.models import (
    DocumentUpload,
    IndexingStatus,
)
from chartroom.knowledge.service import DocumentLibrary, Indexer
from chartroom.shared.errors import ServiceUnavailableError
from chartroom.shared.language import Language
from tests.fakes import (
    FakeEmbedder,
    InMemoryChunkIndex,
    InMemoryKnowledgeUnitOfWork,
    KnowledgeStore,
    RecordingQueue,
)

FIRE_V3 = b"# Fire\n## 1. Purpose\nDefines actions.\n## 2. Alarm\nSound the general alarm."


class World:
    def __init__(self) -> None:
        self.store = KnowledgeStore()
        self.embedder = FakeEmbedder()
        self.index = InMemoryChunkIndex()
        uow = lambda: InMemoryKnowledgeUnitOfWork(self.store)  # noqa: E731
        self.library = DocumentLibrary(uow, RecordingQueue())
        self.indexer = Indexer(uow, build_document_chunker(), self.embedder, self.index)

    async def upload(self, label: str, issued_on: date, content: bytes = FIRE_V3) -> int:
        upload = DocumentUpload("Fire", Language.EN, label, issued_on, "fire.md", content)
        return (await self.library.upload(upload)).id


@pytest.fixture
def world() -> World:
    return World()


async def test_indexing_writes_points_and_chunks_and_activates(world: World) -> None:
    version_id = await world.upload("3", date(2026, 9, 1))
    await world.indexer.index(version_id)

    version = world.store.versions[version_id]
    assert (version.status, version.is_active, version.error) == (
        IndexingStatus.INDEXED,
        True,
        None,
    )
    assert world.index.dimensions == FakeEmbedder.dimensions
    assert set(world.index.points) == {chunk_point_id(version_id, 0), chunk_point_id(version_id, 1)}
    assert [c.chunk.section_path for c in world.store.chunks[version_id]] == [
        "Fire / 1. Purpose",
        "Fire / 2. Alarm",
    ]
    # Эмбеддинг получает фрагмент вместе с путём раздела.
    assert world.embedder.calls == [
        ["Fire / 1. Purpose\n\nDefines actions.", "Fire / 2. Alarm\n\nSound the general alarm."]
    ]
    point = world.index.points[chunk_point_id(version_id, 1)]
    assert (point.title, point.language, len(point.dense)) == ("Fire", Language.EN, 3)
    assert point.sparse.indices


async def test_reindexing_is_idempotent(world: World) -> None:
    version_id = await world.upload("3", date(2026, 9, 1))
    await world.indexer.index(version_id)
    await world.indexer.index(version_id)
    assert len(world.index.points) == 2
    assert len(world.store.chunks[version_id]) == 2


async def test_newer_revision_replaces_active_one_but_older_does_not(world: World) -> None:
    v3 = await world.upload("3", date(2026, 9, 1))
    v4 = await world.upload("4", date(2026, 10, 1), content=FIRE_V3 + b"\nUpdated.")
    v2 = await world.upload("2", date(2026, 1, 1), content=FIRE_V3 + b"\nOld.")
    for version_id in (v3, v4, v2):
        await world.indexer.index(version_id)
    active = {v.label: v.is_active for v in world.store.versions.values()}
    assert active == {"3": False, "4": True, "2": False}
    assert all(v.status is IndexingStatus.INDEXED for v in world.store.versions.values())


async def test_broken_document_fails_without_retry(world: World) -> None:
    version_id = await world.upload("3", date(2026, 9, 1), content=b"   ")
    await world.indexer.index(version_id)
    version = world.store.versions[version_id]
    assert (version.status, version.error) == (
        IndexingStatus.FAILED,
        "Document has no extractable text",
    )
    assert world.index.points == {}


async def test_provider_outage_is_reported_then_retried(world: World) -> None:
    version_id = await world.upload("3", date(2026, 9, 1))
    world.embedder.unavailable = True
    with pytest.raises(ServiceUnavailableError):
        await world.indexer.index(version_id)
    failed = world.store.versions[version_id]
    assert (failed.status, failed.error) == (
        IndexingStatus.FAILED,
        "Embedding provider is unavailable",
    )

    world.embedder.unavailable = False
    await world.indexer.index(version_id)  # повтор задачи
    recovered = world.store.versions[version_id]
    assert (recovered.status, recovered.error, recovered.is_active) == (
        IndexingStatus.INDEXED,
        None,
        True,
    )


async def test_missing_version_is_a_no_op(world: World) -> None:
    await world.indexer.index(999)
    assert world.store.versions == {} and world.index.points == {}


async def test_unexpected_error_never_leaves_version_stuck_in_indexing(world: World) -> None:
    class BrokenIndex(InMemoryChunkIndex):
        async def ensure_collection(self, dimensions: int) -> None:
            raise RuntimeError("collection has another vector size")

    world.indexer = Indexer(
        lambda: InMemoryKnowledgeUnitOfWork(world.store),
        build_document_chunker(),
        world.embedder,
        BrokenIndex(),
    )
    version_id = await world.upload("3", date(2026, 9, 1))
    with pytest.raises(RuntimeError):
        await world.indexer.index(version_id)
    version = world.store.versions[version_id]
    # Наружу — нейтральный текст: детали ошибки остаются в логах worker, а не в API.
    assert (version.status, version.error) == (
        IndexingStatus.FAILED,
        "Internal error during indexing",
    )
