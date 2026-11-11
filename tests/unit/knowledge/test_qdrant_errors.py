from types import SimpleNamespace
from typing import cast

import httpx
import pytest
from qdrant_client import AsyncQdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse

from chartroom.knowledge.adapters.qdrant import QdrantChunkIndex
from chartroom.shared.errors import ServiceUnavailableError


async def test_create_error_other_than_conflict_is_not_swallowed() -> None:
    async def collection_exists(_: str) -> bool:
        return False

    async def create_collection(*_: object, **__: object) -> None:
        raise UnexpectedResponse(422, "Unprocessable", b"{}", httpx.Headers())

    client = SimpleNamespace(
        collection_exists=collection_exists, create_collection=create_collection
    )
    index = QdrantChunkIndex(cast(AsyncQdrantClient, client), "chunks")
    # 409 означал бы «коллекцию создал соседний worker»; любой другой ответ — настоящая ошибка.
    with pytest.raises(ServiceUnavailableError):
        await index.ensure_collection(3)
