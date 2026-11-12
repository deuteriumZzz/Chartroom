"""Вызов генерации Gemini с цепочкой моделей — общий для ответов (qa) и извлечения отчётов.

Одна попытка на модель с коротким таймаутом: вторым шансом служит следующая модель цепочки,
а не повтор к перегруженной (ADR-007). Перебираются только сбои провайдера — 5xx, 429 и сеть;
прочие 4xx означают ошибку нашего запроса, и другая модель её не исправит.
"""

import logging
from collections.abc import Sequence

import httpx
from google import genai
from google.genai import errors, types

from chartroom.shared.errors import ServiceUnavailableError

PER_MODEL_HTTP = types.HttpOptions(timeout=20_000, retry_options=types.HttpRetryOptions(attempts=1))
UNAVAILABLE = "Language model is unavailable"

logger = logging.getLogger(__name__)


async def generate_with_fallback(
    client: genai.Client,
    models: Sequence[str],
    contents: str,
    config: types.GenerateContentConfig,
) -> tuple[types.GenerateContentResponse, str]:
    """Ответ первой модели цепочки, которая смогла ответить, и имя этой модели."""
    for model in models:
        try:
            response = await client.aio.models.generate_content(
                model=model, contents=contents, config=config
            )
        except (errors.ServerError, httpx.HTTPError) as e:
            logger.warning("generation model %s failed: %s", model, _describe(e))
            continue
        except errors.ClientError as e:
            logger.warning("generation model %s failed: %s", model, _describe(e))
            if e.code == 429:
                continue  # исчерпана квота этой модели — следующая
            raise ServiceUnavailableError(UNAVAILABLE) from e
        return response, model
    raise ServiceUnavailableError(UNAVAILABLE)


def _describe(error: Exception) -> str:
    code = getattr(error, "code", None)
    return f"{type(error).__name__} {code}" if code else type(error).__name__
