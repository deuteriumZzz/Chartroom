"""Агент на Gemini function calling: объявления функций, вызовы и ответы на них."""

import html
from collections.abc import Sequence
from importlib import resources

from google import genai
from google.genai import types

from chartroom.agent.domain import TOOLS, ModelTurn, ToolCall, ToolResult
from chartroom.shared.errors import ServiceUnavailableError
from chartroom.shared.gemini import PER_MODEL_HTTP, generate_with_fallback
from chartroom.shared.language import Language

AGENT_PROMPT = "agent.v1"

_DECLARATIONS = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name=tool.name, description=tool.description, parameters_json_schema=tool.parameters
        )
        for tool in TOOLS
    ]
)


class GeminiConversation:
    def __init__(
        self,
        client: genai.Client,
        models: Sequence[str],
        config: types.GenerateContentConfig,
        opening: str,
    ) -> None:
        self._client = client
        self._models = list(models)
        self._config = config
        self._contents = [types.Content(role="user", parts=[types.Part.from_text(text=opening)])]
        self.model: str | None = None

    async def next_turn(self, results: Sequence[ToolResult]) -> ModelTurn:
        if results:
            parts = [
                types.Part.from_function_response(name=r.name, response=r.content) for r in results
            ]
            self._contents.append(types.Content(role="user", parts=parts))
        response, model = await generate_with_fallback(
            self._client, self._models, self._contents, self._config
        )
        # Диалог закрепляется за ответившей моделью: подписи её рассуждений (thought signatures),
        # которые Gemini требует вернуть в следующих запросах, другой модели не подходят.
        self.model, self._models = model, [model]
        content = response.candidates[0].content if response.candidates else None
        if content is not None:
            self._contents.append(content)  # как есть: с подписями рассуждений
        calls = tuple(
            ToolCall(c.name or "", dict(c.args or {})) for c in response.function_calls or []
        )
        parts = content.parts or [] if content is not None else []
        text = "".join(p.text for p in parts if p.text) or None
        return ModelTurn(calls, None if calls else text)


class GeminiAgentModel:
    def __init__(self, client: genai.Client, models: Sequence[str]) -> None:
        if not models:
            raise ValueError("at least one generation model is required")
        self._client = client
        self._models = list(models)
        self.prompt_version = AGENT_PROMPT
        prompt = resources.files("chartroom.agent").joinpath("prompts", f"{AGENT_PROMPT}.md")
        self._config = types.GenerateContentConfig(
            system_instruction=prompt.read_text("utf-8"),
            tools=[_DECLARATIONS],
            temperature=0.0,
            http_options=PER_MODEL_HTTP,
        )

    def start(self, question: str, language: Language) -> GeminiConversation:
        opening = f'<question language="{language}">{html.escape(question)}</question>'
        return GeminiConversation(self._client, self._models, self._config, opening)


class UnconfiguredConversation:
    model: str | None = None

    async def next_turn(self, results: Sequence[ToolResult]) -> ModelTurn:
        raise ServiceUnavailableError("Language model is not configured")


class UnconfiguredAgentModel:
    """Подставляется без GEMINI_API_KEY: API стартует, а вопрос агенту получает 503."""

    prompt_version = AGENT_PROMPT

    def start(self, question: str, language: Language) -> UnconfiguredConversation:
        return UnconfiguredConversation()
