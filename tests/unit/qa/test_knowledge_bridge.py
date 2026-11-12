from datetime import date

from chartroom.bootstrap import build_document_chunker
from chartroom.knowledge.domain.models import DocumentUpload
from chartroom.knowledge.service import ChunkRetriever, DocumentLibrary, Indexer
from chartroom.qa.adapters.knowledge import KnowledgePassageRetriever
from chartroom.qa.domain import Passage
from chartroom.shared.language import Language
from tests.fakes import (
    FakeEmbedder,
    InMemoryChunkIndex,
    InMemoryKnowledgeUnitOfWork,
    KnowledgeStore,
    RecordingQueue,
)


async def test_knowledge_chunks_become_qa_passages() -> None:
    store, embedder, index = KnowledgeStore(), FakeEmbedder(), InMemoryChunkIndex()
    uow = lambda: InMemoryKnowledgeUnitOfWork(store)  # noqa: E731
    upload = DocumentUpload(
        "Fire",
        Language.EN,
        "1",
        date(2026, 1, 1),
        "fire.md",
        b"# Fire\n## 2. Engine room\nClose the fuel valves.",
    )
    version = await DocumentLibrary(uow, RecordingQueue()).upload(upload)
    await Indexer(uow, build_document_chunker(), embedder, index).index(version.id)

    bridge = KnowledgePassageRetriever(ChunkRetriever(uow, embedder, index))
    [passage] = await bridge.retrieve("fuel valves", limit=5)
    assert passage == Passage(
        document_id=version.document_id,
        version_id=version.id,
        title="Fire",
        section_path="Fire / 2. Engine room",
        page=None,
        text="Close the fuel valves.",
        score=passage.score,
        similarity=1.0,
    )
