"""Генерация ответа через Gemini API со structured output."""

from collections.abc import Sequence
from importlib import resources

from google import genai
from google.genai import types
from pydantic import BaseModel

from chartroom.qa.domain import (
    GeneratedAnswer,
    Passage,
    RawCitation,
    render_context,
)
from chartroom.shared.errors import ServiceUnavailableError
from chartroom.shared.gemini import PER_MODEL_HTTP, generate_with_fallback
from chartroom.shared.language import Language

ANSWER_PROMPT = "answer.v2"


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
            http_options=PER_MODEL_HTTP,
        )

    async def generate(
        self, question: str, language: Language, passages: Sequence[Passage]
    ) -> GeneratedAnswer:
        response, model = await generate_with_fallback(
            self._client, self._models, render_context(question, language, passages), self._config
        )
        parsed = response.parsed
        if not isinstance(parsed, _AnswerSchema):
            raise ServiceUnavailableError("Language model returned a malformed answer")
        citations = tuple(RawCitation(c.passage, c.quote) for c in parsed.citations)
        return GeneratedAnswer(parsed.answer.strip(), citations, parsed.refusal, model)


class UnconfiguredAnswerGenerator:
    """Подставляется без GEMINI_API_KEY: API стартует, а вопрос с контекстом получает 503."""

    prompt_version = ANSWER_PROMPT

    async def generate(
        self, question: str, language: Language, passages: Sequence[Passage]
    ) -> GeneratedAnswer:
        raise ServiceUnavailableError("Language model is not configured")
