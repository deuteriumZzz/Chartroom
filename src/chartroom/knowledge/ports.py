"""Что модулю knowledge нужно от внешнего мира. Реализации — в adapters/ и в тестовых фейках."""

from collections.abc import Sequence
from typing import Protocol, Self

from chartroom.knowledge.domain.indexing import IndexedChunk, RetrievedChunk
from chartroom.knowledge.domain.models import (
    Block,
    Document,
    DocumentUpload,
    DocumentVersion,
    IndexingStatus,
    Language,
)
from chartroom.shared.sparse import SparseVector


class DocumentParser(Protocol):
    def parse(self, content: bytes) -> list[Block]:
        """Raises InvalidDocumentError, если содержимое не разбирается."""
        ...


class DocumentRepository(Protocol):
    async def get(self, document_id: int) -> Document | None: ...

    async def find(self, title: str, language: Language) -> Document | None:
        """Поиск по названию без учёта регистра."""
        ...

    async def add(self, title: str, language: Language) -> Document:
        """Raises DocumentAlreadyExistsError при гонке двух загрузок."""
        ...


class VersionRepository(Protocol):
    async def get(self, version_id: int) -> DocumentVersion | None: ...

    async def list_for(self, document_id: int) -> list[DocumentVersion]:
        """Версии документа в порядке загрузки."""
        ...

    async def add(self, document_id: int, upload: DocumentUpload, checksum: str) -> DocumentVersion:
        """Raises DuplicateVersionError или DuplicateFileError при гонке двух загрузок."""
        ...

    async def get_content(self, version_id: int) -> bytes: ...

    async def set_status(
        self, version_id: int, status: IndexingStatus, error: str | None = None
    ) -> None: ...

    async def activate(self, version_id: int) -> None:
        """Делает версию активной, остальные версии документа — неактивными."""
        ...

    async def active_ids(self) -> list[int]:
        """Id активных версий всех документов — по ним фильтруется поиск."""
        ...


class ChunkRepository(Protocol):
    async def replace(self, version_id: int, chunks: Sequence[IndexedChunk]) -> None: ...


class KnowledgeUnitOfWork(Protocol):
    @property
    def documents(self) -> DocumentRepository: ...

    @property
    def versions(self) -> VersionRepository: ...

    @property
    def chunks(self) -> ChunkRepository: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(self, *exc_info: object) -> None: ...

    async def commit(self) -> None: ...


class Embedder(Protocol):
    @property
    def dimensions(self) -> int: ...

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Raises ServiceUnavailableError, если провайдер недоступен."""
        ...


class QueryEmbedder(Protocol):
    async def embed_query(self, text: str) -> list[float]:
        """Raises ServiceUnavailableError, если провайдер недоступен или не настроен."""
        ...


class ChunkIndex(Protocol):
    async def ensure_collection(self, dimensions: int) -> None: ...

    async def upsert(self, chunks: Sequence[IndexedChunk]) -> None:
        """Raises ServiceUnavailableError, если хранилище недоступно."""
        ...


class ChunkSearch(Protocol):
    async def search(
        self,
        dense: Sequence[float],
        sparse: SparseVector,
        version_ids: Sequence[int],
        limit: int,
    ) -> list[RetrievedChunk]:
        """Гибридный поиск среди точек указанных версий. Raises ServiceUnavailableError."""
        ...


class IndexingQueue(Protocol):
    async def enqueue(self, version_id: int) -> None:
        """Raises ServiceUnavailableError, если очередь недоступна."""
        ...
