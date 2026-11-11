import asyncio
import math
import os
import uuid
from collections.abc import AsyncIterator

import pytest
from qdrant_client import AsyncQdrantClient, models

from chartroom.knowledge.adapters.qdrant import (
    DENSE_VECTOR,
    SPARSE_VECTOR,
    IndexConfigurationError,
    QdrantChunkIndex,
)
from chartroom.knowledge.domain.chunking import chunk_blocks
from chartroom.knowledge.domain.indexing import IndexedChunk, chunk_point_id
from chartroom.knowledge.domain.models import Block, Language
from chartroom.shared.errors import ServiceUnavailableError
from chartroom.shared.sparse import SparseVector, bm25_query_vector, bm25_vector

QDRANT_URL = os.environ.get("TEST_QDRANT_URL", "http://localhost:6333")


@pytest.fixture
async def client() -> AsyncIterator[AsyncQdrantClient]:
    qdrant = AsyncQdrantClient(url=QDRANT_URL)
    yield qdrant
    await qdrant.close()


@pytest.fixture
async def index(client: AsyncQdrantClient) -> AsyncIterator[QdrantChunkIndex]:
    collection = f"test_chunks_{uuid.uuid4().hex[:8]}"
    yield QdrantChunkIndex(client, collection)
    await client.delete_collection(collection)


def _chunks(version_id: int) -> list[IndexedChunk]:
    blocks = [
        Block("Close the fuel valves.", ("Fire", "4.4")),
        Block("Sound the alarm.", ("Fire", "4.2")),
    ]
    return [
        IndexedChunk(
            chunk_point_id(version_id, c.index),
            1,
            version_id,
            "Fire",
            Language.EN,
            c,
            (0.1, 0.2, 0.3),
            bm25_vector(c.text),
        )
        for c in chunk_blocks(blocks)
    ]


async def test_collection_is_created_once_even_by_concurrent_workers(
    index: QdrantChunkIndex,
) -> None:
    await asyncio.gather(index.ensure_collection(3), index.ensure_collection(3))
    await index.ensure_collection(3)


async def test_other_dimensions_are_a_configuration_error(index: QdrantChunkIndex) -> None:
    await index.ensure_collection(3)
    with pytest.raises(IndexConfigurationError):
        await index.ensure_collection(768)


async def test_upsert_is_idempotent_and_keeps_citation_payload(
    index: QdrantChunkIndex, client: AsyncQdrantClient
) -> None:
    await index.ensure_collection(3)
    await index.upsert(_chunks(version_id=7))
    await index.upsert(_chunks(version_id=7))
    collection = index._collection
    assert (await client.count(collection)).count == 2

    [point] = await client.retrieve(collection, [str(chunk_point_id(7, 0))], with_vectors=True)
    assert point.payload == {
        "document_id": 1,
        "version_id": 7,
        "title": "Fire",
        "language": "en",
        "section_path": "Fire / 4.4",
        "page": None,
        "chunk_index": 0,
        "text": "Close the fuel valves.",
    }
    vectors = point.vector
    assert isinstance(vectors, dict)
    norm = math.sqrt(0.1**2 + 0.2**2 + 0.3**2)  # для cosine Qdrant хранит нормализованный вектор
    assert vectors[DENSE_VECTOR] == pytest.approx([0.1 / norm, 0.2 / norm, 0.3 / norm], rel=1e-4)
    sparse = vectors[SPARSE_VECTOR]
    assert isinstance(sparse, models.SparseVector)
    assert sparse.indices == list(bm25_vector("Close the fuel valves.").indices)


async def test_unreachable_store_is_service_unavailable() -> None:
    dead = QdrantChunkIndex(
        AsyncQdrantClient(url="http://localhost:1", timeout=1, check_compatibility=False), "chunks"
    )
    with pytest.raises(ServiceUnavailableError):
        await dead.ensure_collection(3)
    with pytest.raises(ServiceUnavailableError):
        await dead.upsert(_chunks(version_id=1))
    with pytest.raises(ServiceUnavailableError):
        await dead.search((1.0, 0.0, 0.0), bm25_query_vector("fire"), [1], limit=5)


def _version(version_id: int, texts: list[str]) -> list[IndexedChunk]:
    blocks = [Block(text, ("Fire", f"{n}")) for n, text in enumerate(texts, 1)]
    return [
        # Одинаковый dense у всех фрагментов: порядок задаёт лексическая часть.
        IndexedChunk(
            chunk_point_id(version_id, c.index),
            1,
            version_id,
            "Fire",
            Language.EN,
            c,
            (1.0, 0.0, 0.0),
            bm25_vector(c.text),
        )
        for c in chunk_blocks(blocks)
    ]


async def test_hybrid_search_ranks_keyword_match_within_active_versions(
    index: QdrantChunkIndex,
) -> None:
    await index.ensure_collection(3)
    await index.upsert(_version(1, ["Sound the general alarm.", "Close the fuel valves."]))
    await index.upsert(
        _version(2, ["Muster at the lifeboat station.", "Close the fuel valves now."])
    )

    found = await index.search((1.0, 0.0, 0.0), bm25_query_vector("fuel valves"), [2], limit=5)
    assert {chunk.version_id for chunk in found} == {2}
    assert found[0].text == "Close the fuel valves now."
    assert (found[0].section_path, found[0].language, found[0].page) == (
        "Fire / 2",
        Language.EN,
        None,
    )
    assert found[0].score >= found[-1].score


async def test_question_without_words_uses_dense_search_only(index: QdrantChunkIndex) -> None:
    await index.ensure_collection(3)
    await index.upsert(_version(1, ["Sound the general alarm."]))
    found = await index.search((1.0, 0.0, 0.0), SparseVector((), ()), [1], limit=5)
    assert [chunk.text for chunk in found] == ["Sound the general alarm."]
