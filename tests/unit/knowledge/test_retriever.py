from datetime import date

import pytest

from chartroom.bootstrap import build_document_chunker
from chartroom.knowledge.adapters.gemini import UnconfiguredQueryEmbedder
from chartroom.knowledge.domain.models import DocumentUpload
from chartroom.knowledge.service import ChunkRetriever, DocumentLibrary, Indexer
from chartroom.shared.errors import ServiceUnavailableError
from chartroom.shared.language import Language
from tests.fakes import (
    FakeEmbedder,
    InMemoryChunkIndex,
    InMemoryKnowledgeUnitOfWork,
    KnowledgeStore,
    RecordingQueue,
)

FIRE_V1 = (
    b"# Fire\n## 1. Alarm\nSound the general alarm.\n## 2. Engine room\nClose the fuel valves."
)
FIRE_V2 = (
    b"# Fire\n## 1. Alarm\nSound the general alarm twice.\n## 2. Engine room\nStop ventilation."
)


class World:
    def __init__(self) -> None:
        self.store = KnowledgeStore()
        self.embedder = FakeEmbedder()
        self.index = InMemoryChunkIndex()
        uow = lambda: InMemoryKnowledgeUnitOfWork(self.store)  # noqa: E731
        self.library = DocumentLibrary(uow, RecordingQueue())
        self.indexer = Indexer(uow, build_document_chunker(), self.embedder, self.index)
        self.retriever = ChunkRetriever(uow, self.embedder, self.index)

    async def publish(self, label: str, issued_on: date, content: bytes) -> int:
        upload = DocumentUpload("Fire", Language.EN, label, issued_on, "fire.md", content)
        version = await self.library.upload(upload)
        await self.indexer.index(version.id)
        return version.id


async def test_search_sees_only_the_active_version() -> None:
    world = World()
    v1 = await world.publish("1", date(2026, 1, 1), FIRE_V1)
    v2 = await world.publish("2", date(2026, 6, 1), FIRE_V2)

    found = await world.retriever.retrieve("fuel valves", limit=5)
    assert {chunk.version_id for chunk in found} == {v2}
    assert v1 in {p.version_id for p in world.index.points.values()}  # старая версия не потеряна
    assert world.embedder.queries == ["fuel valves"]


async def test_search_returns_citation_data() -> None:
    world = World()
    await world.publish("1", date(2026, 1, 1), FIRE_V1)
    [best, *_] = await world.retriever.retrieve("close the fuel valves", limit=1)
    assert (best.title, best.section_path, best.text) == (
        "Fire",
        "Fire / 2. Engine room",
        "Close the fuel valves.",
    )


async def test_empty_library_skips_the_embedding_provider() -> None:
    world = World()
    assert await world.retriever.retrieve("anything", limit=5) == []
    assert world.embedder.queries == []


async def test_search_without_api_key_is_service_unavailable() -> None:
    world = World()
    await world.publish("1", date(2026, 1, 1), FIRE_V1)
    retriever = ChunkRetriever(
        lambda: InMemoryKnowledgeUnitOfWork(world.store), UnconfiguredQueryEmbedder(), world.index
    )
    with pytest.raises(ServiceUnavailableError, match="not configured"):
        await retriever.retrieve("fire", limit=5)
