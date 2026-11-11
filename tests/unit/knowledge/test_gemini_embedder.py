from collections.abc import Sequence
from types import SimpleNamespace
from typing import cast

import httpx
import pytest
from google import genai
from google.genai import errors, types

from chartroom.knowledge.adapters.gemini import GeminiEmbedder
from chartroom.shared.errors import ServiceUnavailableError


class StubModels:
    def __init__(self, failure: Exception | None = None, drop_last: bool = False) -> None:
        self.calls: list[tuple[str, list[str], types.EmbedContentConfig]] = []
        self._failure = failure
        self._drop_last = drop_last

    async def embed_content(
        self, *, model: str, contents: Sequence[str], config: types.EmbedContentConfig
    ) -> types.EmbedContentResponse:
        self.calls.append((model, list(contents), config))
        if self._failure:
            raise self._failure
        count = len(contents) - 1 if self._drop_last else len(contents)
        embeddings = [types.ContentEmbedding(values=[float(len(t)), 0.5]) for t in contents[:count]]
        return types.EmbedContentResponse(embeddings=embeddings)


def _embedder(models: StubModels, batch_size: int = 2) -> GeminiEmbedder:
    client = cast(genai.Client, SimpleNamespace(aio=SimpleNamespace(models=models)))
    return GeminiEmbedder(client, "gemini-embedding-001", dimensions=2, batch_size=batch_size)


async def test_texts_are_embedded_in_batches_as_documents() -> None:
    models = StubModels()
    vectors = await _embedder(models).embed_documents(["a", "bb", "ccc", "dddd", "eeeee"])
    assert vectors == [[1.0, 0.5], [2.0, 0.5], [3.0, 0.5], [4.0, 0.5], [5.0, 0.5]]
    assert [len(contents) for _, contents, _ in models.calls] == [2, 2, 1]
    model, _, config = models.calls[0]
    assert (model, config.task_type, config.output_dimensionality) == (
        "gemini-embedding-001",
        "RETRIEVAL_DOCUMENT",
        2,
    )
    assert _embedder(models).dimensions == 2


@pytest.mark.parametrize(
    "failure",
    [
        errors.ServerError(503, {"error": {"message": "overloaded"}}),
        errors.ClientError(429, {"error": {"message": "quota"}}),
        httpx.ConnectError("network is down"),
    ],
)
async def test_provider_failures_become_service_unavailable(failure: Exception) -> None:
    with pytest.raises(ServiceUnavailableError, match="Embedding provider is unavailable"):
        await _embedder(StubModels(failure)).embed_documents(["text"])


async def test_incomplete_response_is_rejected() -> None:
    with pytest.raises(ServiceUnavailableError, match="incomplete"):
        await _embedder(StubModels(drop_last=True)).embed_documents(["a", "b"])


async def test_query_is_embedded_as_retrieval_query() -> None:
    models = StubModels()
    assert await _embedder(models).embed_query("fire") == [4.0, 0.5]
    _, contents, config = models.calls[0]
    assert (contents, config.task_type) == (["fire"], "RETRIEVAL_QUERY")
