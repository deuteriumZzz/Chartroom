"""Извлечение полей отчёта из свободного текста через Gemini (JSON по схеме шаблона)."""

import html
import json
from collections.abc import Sequence
from importlib import resources

from google import genai
from google.genai import types

from chartroom.reports.domain import ReportData, ReportTemplate
from chartroom.shared.errors import ServiceUnavailableError
from chartroom.shared.gemini import PER_MODEL_HTTP, generate_with_fallback

EXTRACT_PROMPT = "extract.v1"


def render_request(text: str, template: ReportTemplate) -> str:
    # Текст отчёта — недоверенные данные: экранирование не даёт ему закрыть тег и стать правилами.
    schema = json.dumps(template.schema, ensure_ascii=False)
    return f"<schema>{html.escape(schema)}</schema>\n<report>{html.escape(text)}</report>"


class GeminiReportExtractor:
    def __init__(self, client: genai.Client, models: Sequence[str]) -> None:
        self._client = client
        self._models = list(models)
        prompt = resources.files("chartroom.reports").joinpath("prompts", f"{EXTRACT_PROMPT}.md")
        self._config = types.GenerateContentConfig(
            system_instruction=prompt.read_text("utf-8"),
            response_mime_type="application/json",
            temperature=0.0,
            http_options=PER_MODEL_HTTP,
        )

    async def extract(self, text: str, template: ReportTemplate) -> ReportData:
        response, _ = await generate_with_fallback(
            self._client, self._models, render_request(text, template), self._config
        )
        try:
            data = json.loads(response.text or "")
        except json.JSONDecodeError as e:
            raise ServiceUnavailableError("Language model returned a malformed report") from e
        if not isinstance(data, dict):
            raise ServiceUnavailableError("Language model returned a malformed report")
        return data  # что бы ни вернула модель, дальше это проверит validate() по схеме шаблона


class UnconfiguredReportExtractor:
    async def extract(self, text: str, template: ReportTemplate) -> ReportData:
        raise ServiceUnavailableError("Language model is not configured")
