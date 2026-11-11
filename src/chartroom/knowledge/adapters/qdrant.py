from collections.abc import Sequence

from qdrant_client import AsyncQdrantClient, models
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

from chartroom.knowledge.domain.indexing import IndexedChunk
from chartroom.shared.errors import ServiceUnavailableError

DENSE_VECTOR = "dense"
SPARSE_VECTOR = "bm25"
_UNAVAILABLE = "Vector store is unavailable"


class IndexConfigurationError(RuntimeError):
    """Коллекция есть, но другой размерности: модель эмбеддингов сменили без переиндексации."""


class QdrantChunkIndex:
    """Коллекция фрагментов: dense-вектор (cosine) и sparse BM25 с IDF на стороне Qdrant.

    Активную версию документа здесь не храним: это знает только Postgres, а поиск фильтрует
    точки по version_id активных версий. Так два хранилища не могут рассинхронизироваться.
    """

    def __init__(self, client: AsyncQdrantClient, collection: str) -> None:
        self._client = client
        self._collection = collection

    async def ensure_collection(self, dimensions: int) -> None:
        try:
            if not await self._client.collection_exists(self._collection):
                await self._create(dimensions)
            info = await self._client.get_collection(self._collection)
        except (UnexpectedResponse, ResponseHandlingException) as e:
            raise ServiceUnavailableError(_UNAVAILABLE) from e
        vectors = info.config.params.vectors
        dense = vectors.get(DENSE_VECTOR) if isinstance(vectors, dict) else None
        if dense is None or dense.size != dimensions:
            raise IndexConfigurationError(
                f"Collection {self._collection!r} does not have a {dimensions}-dim "
                f"'{DENSE_VECTOR}' vector: recreate it and reindex"
            )

    async def upsert(self, chunks: Sequence[IndexedChunk]) -> None:
        points = [
            models.PointStruct(
                id=str(item.point_id),
                vector={
                    DENSE_VECTOR: list(item.dense),
                    SPARSE_VECTOR: models.SparseVector(
                        indices=list(item.sparse.indices), values=list(item.sparse.values)
                    ),
                },
                payload={
                    "document_id": item.document_id,
                    "version_id": item.version_id,
                    "title": item.title,
                    "language": item.language.value,
                    "section_path": item.chunk.section_path,
                    "page": item.chunk.page,
                    "chunk_index": item.chunk.index,
                    "text": item.chunk.text,
                },
            )
            for item in chunks
        ]
        try:
            await self._client.upsert(self._collection, points=points, wait=True)
        except (UnexpectedResponse, ResponseHandlingException) as e:
            raise ServiceUnavailableError(_UNAVAILABLE) from e

    async def _create(self, dimensions: int) -> None:
        try:
            await self._client.create_collection(
                self._collection,
                vectors_config={
                    DENSE_VECTOR: models.VectorParams(
                        size=dimensions, distance=models.Distance.COSINE
                    )
                },
                sparse_vectors_config={
                    SPARSE_VECTOR: models.SparseVectorParams(modifier=models.Modifier.IDF)
                },
            )
        except UnexpectedResponse as e:
            if e.status_code != 409:  # 409 — коллекцию только что создал параллельный worker
                raise
        await self._client.create_payload_index(
            self._collection, "version_id", models.PayloadSchemaType.INTEGER
        )
