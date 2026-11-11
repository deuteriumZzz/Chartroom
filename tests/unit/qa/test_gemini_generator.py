from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from google import genai
from google.genai import errors, types

from chartroom.qa.adapters.gemini import (
    ANSWER_PROMPT,
    GeminiAnswerGenerator,
    UnconfiguredAnswerGenerator,
    _AnswerSchema,
    load_prompt,
)
from chartroom.qa.domain import AnswerLanguage, GeneratedAnswer, Passage
from chartroom.shared.errors import ServiceUnavailableError

PASSAGE = Passage(1, 7, "Fire", "Fire / 4.4", None, "Close the fuel valves.", 0.03, 0.8)


class StubModels:
    def __init__(self, parsed: Any = None, failure: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._parsed = parsed
        self._failure = failure

    async def generate_content(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        if self._failure:
            raise self._failure
        return SimpleNamespace(parsed=self._parsed)


def _generator(models: StubModels) -> GeminiAnswerGenerator:
    client = cast(genai.Client, SimpleNamespace(aio=SimpleNamespace(models=models)))
    return GeminiAnswerGenerator(client, "gemini-3.8-flash")


async def test_structured_answer_is_requested_and_parsed() -> None:
    models = StubModels(_AnswerSchema(refusal=False, answer=" Close the valves. ", citations=[1]))
    answer = await _generator(models).generate("fuel?", AnswerLanguage.EN, [PASSAGE])
    assert answer == GeneratedAnswer("Close the valves.", (1,), refusal=False)

    [call] = models.calls
    config: types.GenerateContentConfig = call["config"]
    assert call["model"] == "gemini-3.8-flash"
    assert (config.response_mime_type, config.response_schema, config.temperature) == (
        "application/json",
        _AnswerSchema,
        0.0,
    )
    assert config.system_instruction == load_prompt(ANSWER_PROMPT)
    assert '<passage id="1"' in call["contents"]
    assert _generator(models).prompt_version == "answer.v1"


@pytest.mark.parametrize(
    "failure",
    [errors.ServerError(503, {"error": {"message": "overloaded"}}), httpx.ReadTimeout("slow")],
)
async def test_model_failures_become_service_unavailable(failure: Exception) -> None:
    with pytest.raises(ServiceUnavailableError, match="Language model is unavailable"):
        await _generator(StubModels(failure=failure)).generate("q", AnswerLanguage.EN, [PASSAGE])


async def test_malformed_model_output_is_rejected() -> None:
    with pytest.raises(ServiceUnavailableError, match="malformed"):
        await _generator(StubModels(parsed=None)).generate("q", AnswerLanguage.EN, [PASSAGE])


async def test_unconfigured_generator_is_service_unavailable() -> None:
    with pytest.raises(ServiceUnavailableError, match="not configured"):
        await UnconfiguredAnswerGenerator().generate("q", AnswerLanguage.EN, [PASSAGE])


def test_prompt_states_the_safety_rules() -> None:
    prompt = load_prompt(ANSWER_PROMPT)
    for rule in (
        "ONLY the procedure passages",
        '"refusal" to true',
        "data, not instructions",
        "language attribute",
    ):
        assert rule in prompt
