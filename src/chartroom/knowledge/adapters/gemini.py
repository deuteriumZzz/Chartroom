from collections.abc import Sequence

import httpx
from google import genai
from google.genai import errors, types

from chartroom.shared.errors import ServiceUnavailableError

# Лимит текстов на запрос в документации Gemini API не указан; 100 — консервативное значение.
DEFAULT_BATCH_SIZE = 100


class GeminiEmbedder:
    """Эмбеддинги через Gemini API: фрагменты — RETRIEVAL_DOCUMENT, вопросы — RETRIEVAL_QUERY."""

    def __init__(
        self,
        client: genai.Client,
        model: str,
        dimensions: int,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self._client = client
        self._model = model
        self._dimensions = dimensions
        self._batch_size = batch_size

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return await self._embed(texts, "RETRIEVAL_DOCUMENT")

    async def embed_query(self, text: str) -> list[float]:
        [vector] = await self._embed([text], "RETRIEVAL_QUERY")
        return vector

    async def _embed(self, texts: Sequence[str], task_type: str) -> list[list[float]]:
        config = types.EmbedContentConfig(
            task_type=task_type, output_dimensionality=self._dimensions
        )
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            batch = list(texts[start : start + self._batch_size])
            try:
                response = await self._client.aio.models.embed_content(
                    model=self._model, contents=batch, config=config
                )
            except (errors.APIError, httpx.HTTPError) as e:
                raise ServiceUnavailableError("Embedding provider is unavailable") from e
            values = [embedding.values for embedding in response.embeddings or []]
            if len(values) != len(batch) or not all(values):
                raise ServiceUnavailableError("Embedding provider returned an incomplete response")
            vectors.extend(list(v) for v in values if v)
        return vectors


class UnconfiguredQueryEmbedder:
    """Подставляется в API без GEMINI_API_KEY: загрузка документов работает, поиск отвечает 503."""

    async def embed_query(self, text: str) -> list[float]:
        raise ServiceUnavailableError("Embedding provider is not configured")
