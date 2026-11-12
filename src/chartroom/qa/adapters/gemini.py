"""Генерация ответа через Gemini API со structured output."""

import logging
from collections.abc import Sequence
from importlib import resources

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel

from chartroom.qa.domain import (
    AnswerLanguage,
    GeneratedAnswer,
    Passage,
    RawCitation,
    render_context,
)
from chartroom.shared.errors import ServiceUnavailableError

ANSWER_PROMPT = "answer.v2"
# Одна попытка на модель с коротким таймаутом: вторым шансом служит следующая модель цепочки,
# а не повтор к перегруженной. Худший случай — около 20 с на модель, а не минуты ожидания.
_PER_MODEL = types.HttpOptions(timeout=20_000, retry_options=types.HttpRetryOptions(attempts=1))

logger = logging.getLogger(__name__)


def load_prompt(version: str) -> str:
    """Промпты — версионированные файлы в qa/prompts, а не строки в коде."""
    return resources.files("chartroom.qa").joinpath("prompts", f"{version}.md").read_text("utf-8")


class _CitationSchema(BaseModel):
    passage: int
    quote: str


class _AnswerSchema(BaseModel):
    refusal: bool
    answer: str
    citations: list[_CitationSchema]


class GeminiAnswerGenerator:
    def __init__(
        self, client: genai.Client, models: Sequence[str], prompt_version: str = ANSWER_PROMPT
    ) -> None:
        if not models:
            raise ValueError("at least one generation model is required")
        self._client = client
        self._models = list(models)
        self.prompt_version = prompt_version
        self._config = types.GenerateContentConfig(
            system_instruction=load_prompt(prompt_version),
            response_mime_type="application/json",
            response_schema=_AnswerSchema,
            temperature=0.0,  # ответ по документам, а не творчество
            http_options=_PER_MODEL,
        )

    async def generate(
        self, question: str, language: AnswerLanguage, passages: Sequence[Passage]
    ) -> GeneratedAnswer:
        contents = render_context(question, language, passages)
        for model in self._models:
            try:
                response = await self._client.aio.models.generate_content(
                    model=model, contents=contents, config=self._config
                )
            except (errors.ServerError, httpx.HTTPError) as e:
                logger.warning("generation model %s failed: %s", model, _describe(e))
                continue  # перегрузка или сбой провайдера — пробуем следующую модель
            except errors.ClientError as e:
                logger.warning("generation model %s failed: %s", model, _describe(e))
                if e.code == 429:
                    continue  # исчерпана квота этой модели — следующая
                raise ServiceUnavailableError("Language model is unavailable") from e
            return _parse(response, model)
        raise ServiceUnavailableError("Language model is unavailable")


def _describe(error: Exception) -> str:
    code = getattr(error, "code", None)
    return f"{type(error).__name__} {code}" if code else type(error).__name__


def _parse(response: types.GenerateContentResponse, model: str) -> GeneratedAnswer:
    parsed = response.parsed
    if not isinstance(parsed, _AnswerSchema):
        raise ServiceUnavailableError("Language model returned a malformed answer")
    citations = tuple(RawCitation(c.passage, c.quote) for c in parsed.citations)
    return GeneratedAnswer(parsed.answer.strip(), citations, parsed.refusal, model)


class UnconfiguredAnswerGenerator:
    """Подставляется без GEMINI_API_KEY: API стартует, а вопрос с контекстом получает 503."""

    prompt_version = ANSWER_PROMPT

    async def generate(
        self, question: str, language: AnswerLanguage, passages: Sequence[Passage]
    ) -> GeneratedAnswer:
        raise ServiceUnavailableError("Language model is not configured")
