"""Контракт хранилища knowledge: фейк и Postgres должны вести себя одинаково."""

from collections.abc import Callable
from datetime import date

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from chartroom.knowledge.adapters.persistence import ChunkRecord, SqlKnowledgeUnitOfWork
from chartroom.knowledge.domain.chunking import chunk_blocks
from chartroom.knowledge.domain.indexing import IndexedChunk, chunk_point_id
from chartroom.knowledge.domain.models import (
    Block,
    DocumentAlreadyExistsError,
    DocumentUpload,
    DuplicateFileError,
    DuplicateVersionError,
    IndexingStatus,
    Language,
)
from chartroom.knowledge.ports import KnowledgeUnitOfWork
from chartroom.shared.sparse import bm25_vector
from tests.fakes import InMemoryKnowledgeUnitOfWork, KnowledgeStore

UowFactory = Callable[[], KnowledgeUnitOfWork]


def _upload(label: str, content: bytes, issued_on: date = date(2026, 9, 1)) -> DocumentUpload:
    return DocumentUpload("Fire", Language.EN, label, issued_on, "fire.md", content)


def _indexed(version_id: int, document_id: int) -> list[IndexedChunk]:
    chunks = chunk_blocks([Block("Text a.", ("Fire", "1")), Block("Text b.", ("Fire", "2"))])
    return [
        IndexedChunk(
            chunk_point_id(version_id, c.index),
            document_id,
            version_id,
            "Fire",
            Language.EN,
            c,
            (0.1, 0.2),
            bm25_vector(c.text),
        )
        for c in chunks
    ]


@pytest.fixture(params=["in-memory", "sql"])
def uow_factory(
    request: pytest.FixtureRequest, session_factory: async_sessionmaker[AsyncSession]
) -> UowFactory:
    if request.param == "sql":
        return lambda: SqlKnowledgeUnitOfWork(session_factory)
    store = KnowledgeStore()
    return lambda: InMemoryKnowledgeUnitOfWork(store)


async def test_documents_are_found_by_title_ignoring_case(uow_factory: UowFactory) -> None:
    async with uow_factory() as uow:
        added = await uow.documents.add("Fire Safety", Language.EN)
        await uow.commit()
    async with uow_factory() as uow:
        assert await uow.documents.find("FIRE safety", Language.EN) == added
        assert await uow.documents.find("Fire Safety", Language.RU) is None
        assert await uow.documents.get(added.id) == added
        assert await uow.documents.get(999) is None
        with pytest.raises(DocumentAlreadyExistsError):
            await uow.documents.add("fire safety", Language.EN)


async def test_versions_lifecycle(uow_factory: UowFactory) -> None:
    async with uow_factory() as uow:
        document = await uow.documents.add("Fire", Language.EN)
        v3 = await uow.versions.add(document.id, _upload("3", b"three"), "c3")
        v4 = await uow.versions.add(document.id, _upload("4", b"four"), "c4")
        await uow.commit()
    assert (v3.status, v3.is_active, v3.error) == (IndexingStatus.PENDING, False, None)
    assert v3.uploaded_at.tzinfo is not None

    async with uow_factory() as uow:
        assert [v.label for v in await uow.versions.list_for(document.id)] == ["3", "4"]
        assert await uow.versions.get_content(v4.id) == b"four"
        await uow.versions.set_status(v3.id, IndexingStatus.FAILED, "boom")
        await uow.versions.activate(v3.id)
        await uow.versions.activate(v4.id)
        await uow.commit()

    async with uow_factory() as uow:
        assert await uow.versions.get(999) is None
        failed = await uow.versions.get(v3.id)
        assert failed is not None
        assert (failed.status, failed.error, failed.is_active) == (
            IndexingStatus.FAILED,
            "boom",
            False,
        )
        await uow.versions.set_status(v3.id, IndexingStatus.INDEXED)
        await uow.commit()

    async with uow_factory() as uow:
        versions = {v.label: v for v in await uow.versions.list_for(document.id)}
        assert (versions["3"].error, versions["4"].is_active) == (None, True)


@pytest.mark.parametrize(
    ("label", "checksum", "error"),
    [("3", "other", DuplicateVersionError), ("4", "c3", DuplicateFileError)],
)
async def test_duplicate_versions_are_rejected(
    uow_factory: UowFactory, label: str, checksum: str, error: type[Exception]
) -> None:
    async with uow_factory() as uow:
        document = await uow.documents.add("Fire", Language.EN)
        await uow.versions.add(document.id, _upload("3", b"three"), "c3")
        await uow.commit()
    async with uow_factory() as uow:
        with pytest.raises(error):
            await uow.versions.add(document.id, _upload(label, b"x"), checksum)


async def test_uncommitted_upload_is_discarded(uow_factory: UowFactory) -> None:
    async with uow_factory() as uow:
        await uow.documents.add("Fire", Language.EN)
    async with uow_factory() as uow:
        assert await uow.documents.find("Fire", Language.EN) is None


async def test_replacing_chunks_is_repeatable(uow_factory: UowFactory) -> None:
    async with uow_factory() as uow:
        document = await uow.documents.add("Fire", Language.EN)
        version = await uow.versions.add(document.id, _upload("3", b"three"), "c3")
        await uow.chunks.replace(version.id, _indexed(version.id, document.id))
        await uow.chunks.replace(version.id, _indexed(version.id, document.id))
        await uow.commit()


async def test_sql_replace_keeps_one_row_per_chunk(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with SqlKnowledgeUnitOfWork(session_factory) as uow:
        document = await uow.documents.add("Fire", Language.EN)
        version = await uow.versions.add(document.id, _upload("3", b"three"), "c3")
        for _ in range(2):
            await uow.chunks.replace(version.id, _indexed(version.id, document.id))
        await uow.commit()
        count = await uow.session.scalar(
            select(func.count()).where(ChunkRecord.version_id == version.id)
        )
    assert count == 2
