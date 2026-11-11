import hashlib
from collections.abc import Callable, Mapping
from dataclasses import replace

from chartroom.knowledge.domain.chunking import chunk_blocks
from chartroom.knowledge.domain.indexing import IndexedChunk, chunk_point_id, embedding_input
from chartroom.knowledge.domain.models import (
    MAX_UPLOAD_BYTES,
    Chunk,
    Document,
    DocumentFormat,
    DocumentNotFoundError,
    DocumentOverview,
    DocumentUpload,
    DocumentVersion,
    EmptyDocumentError,
    FileTooLargeError,
    IndexingStatus,
    detect_format,
    ensure_new_version,
    normalize_label,
    normalize_title,
    safe_filename,
    should_activate,
)
from chartroom.knowledge.ports import (
    ChunkIndex,
    DocumentParser,
    Embedder,
    IndexingQueue,
    KnowledgeUnitOfWork,
)
from chartroom.shared.errors import DomainError, ServiceUnavailableError
from chartroom.shared.sparse import bm25_vector

UowFactory = Callable[[], KnowledgeUnitOfWork]


class DocumentChunker:
    """Разбор документа и нарезка на фрагменты: формат по сигнатуре, затем нужный парсер."""

    def __init__(self, parsers: Mapping[DocumentFormat, DocumentParser]) -> None:
        self._parsers = parsers

    def chunk(self, filename: str, content: bytes) -> list[Chunk]:
        document_format = detect_format(filename, content)
        chunks = chunk_blocks(self._parsers[document_format].parse(content))
        if not chunks:
            raise EmptyDocumentError
        return chunks


class DocumentLibrary:
    """Загрузка документов и статус их индексации."""

    def __init__(self, uow_factory: UowFactory, queue: IndexingQueue) -> None:
        self._uow_factory = uow_factory
        self._queue = queue

    async def upload(self, upload: DocumentUpload) -> DocumentVersion:
        if len(upload.content) > MAX_UPLOAD_BYTES:
            raise FileTooLargeError
        upload = replace(
            upload,
            title=normalize_title(upload.title),
            label=normalize_label(upload.label),
            filename=safe_filename(upload.filename),
        )
        detect_format(upload.filename, upload.content)  # подменённый файл отсекаем до сохранения
        checksum = hashlib.sha256(upload.content).hexdigest()
        async with self._uow_factory() as uow:
            document = await uow.documents.find(upload.title, upload.language)
            if document is None:
                document = await uow.documents.add(upload.title, upload.language)
            ensure_new_version(await uow.versions.list_for(document.id), upload.label, checksum)
            version = await uow.versions.add(document.id, upload, checksum)
            await uow.commit()
        # В очередь — только после commit: иначе worker может не найти ещё не сохранённую версию.
        await self._queue.enqueue(version.id)
        return version

    async def overview(self, document_id: int) -> DocumentOverview:
        async with self._uow_factory() as uow:
            document = await uow.documents.get(document_id)
            if document is None:
                raise DocumentNotFoundError
            return DocumentOverview(document, await uow.versions.list_for(document_id))


class Indexer:
    """Индексация версии документа: разбор, эмбеддинги, запись в индекс. Выполняется в worker."""

    def __init__(
        self,
        uow_factory: UowFactory,
        chunker: DocumentChunker,
        embedder: Embedder,
        index: ChunkIndex,
    ) -> None:
        self._uow_factory = uow_factory
        self._chunker = chunker
        self._embedder = embedder
        self._index = index

    async def index(self, version_id: int) -> None:
        async with self._uow_factory() as uow:
            version = await uow.versions.get(version_id)
            document = await uow.documents.get(version.document_id) if version else None
            if version is None or document is None:
                return  # версию удалили до запуска задачи — индексировать нечего
            content = await uow.versions.get_content(version_id)
            await uow.versions.set_status(version_id, IndexingStatus.INDEXING)
            await uow.commit()

        try:
            indexed = await self._write_to_index(document, version, content)
        except DomainError as e:  # битый файл или нет текста — повтор не поможет
            await self.mark_failed(version_id, str(e))
            return
        except ServiceUnavailableError as e:
            # Причина видна в API сразу; worker повторит задачу, и при успехе статус сменится.
            await self.mark_failed(version_id, str(e))
            raise
        except Exception:
            # Что бы ни случилось, версия не должна навсегда остаться в статусе indexing.
            await self.mark_failed(version_id, "Internal error during indexing")
            raise

        async with self._uow_factory() as uow:
            await uow.chunks.replace(version_id, indexed)
            versions = await uow.versions.list_for(version.document_id)
            active = next((v for v in versions if v.is_active), None)
            if should_activate(version, active):
                await uow.versions.activate(version_id)
            await uow.versions.set_status(version_id, IndexingStatus.INDEXED)
            await uow.commit()

    async def mark_failed(self, version_id: int, reason: str) -> None:
        async with self._uow_factory() as uow:
            await uow.versions.set_status(version_id, IndexingStatus.FAILED, reason)
            await uow.commit()

    async def _write_to_index(
        self, document: Document, version: DocumentVersion, content: bytes
    ) -> list[IndexedChunk]:
        chunks = self._chunker.chunk(version.filename, content)
        vectors = await self._embedder.embed_documents(
            [embedding_input(document.title, chunk) for chunk in chunks]
        )
        indexed = [
            IndexedChunk(
                point_id=chunk_point_id(version.id, chunk.index),
                document_id=document.id,
                version_id=version.id,
                title=document.title,
                language=document.language,
                chunk=chunk,
                dense=tuple(vector),
                sparse=bm25_vector(chunk.text),
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        await self._index.ensure_collection(self._embedder.dimensions)
        await self._index.upsert(indexed)
        return indexed
