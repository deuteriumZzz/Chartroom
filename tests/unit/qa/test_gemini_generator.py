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
    _CitationSchema,
    load_prompt,
)
from chartroom.qa.domain import AnswerLanguage, GeneratedAnswer, Passage, RawCitation
from chartroom.shared.errors import ServiceUnavailableError

PASSAGE = Passage(1, 7, "Fire", "Fire / 4.4", None, "Close the fuel valves.", 0.03, 0.8)
SCHEMA = _AnswerSchema(
    refusal=False,
    answer=" Close the valves. ",
    citations=[_CitationSchema(passage=1, quote="Close the fuel valves")],
)
OVERLOADED = errors.ServerError(503, {"error": {"message": "high demand"}})


class StubModels:
    """Отвечает по модели: исключение или разобранный ответ."""

    def __init__(self, outcomes: dict[str, Any]) -> None:
        self.calls: list[dict[str, Any]] = []
        self._outcomes = outcomes

    async def generate_content(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        outcome = self._outcomes[kwargs["model"]]
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(parsed=outcome)


def _generator(
    models: StubModels, chain: tuple[str, ...] = ("primary", "fallback")
) -> GeminiAnswerGenerator:
    client = cast(genai.Client, SimpleNamespace(aio=SimpleNamespace(models=models)))
    return GeminiAnswerGenerator(client, chain)


async def _ask(generator: GeminiAnswerGenerator) -> GeneratedAnswer:
    return await generator.generate("fuel?", AnswerLanguage.EN, [PASSAGE])


async def test_structured_answer_is_requested_from_the_first_model() -> None:
    models = StubModels({"primary": SCHEMA})
    generator = _generator(models)
    assert await _ask(generator) == GeneratedAnswer(
        "Close the valves.", (RawCitation(1, "Close the fuel valves"),), False, "primary"
    )
    [call] = models.calls
    config: types.GenerateContentConfig = call["config"]
    assert (config.response_mime_type, config.response_schema, config.temperature) == (
        "application/json",
        _AnswerSchema,
        0.0,
    )
    assert config.system_instruction == load_prompt(ANSWER_PROMPT)
    assert config.http_options is not None and config.http_options.timeout == 20_000
    assert '<passage id="1"' in call["contents"]
    assert generator.prompt_version == "answer.v2"


@pytest.mark.parametrize(
    "failure",
    [
        OVERLOADED,
        errors.ClientError(429, {"error": {"message": "quota"}}),
        httpx.ReadTimeout("slow"),
    ],
)
async def test_overloaded_model_falls_back_to_the_next(failure: Exception) -> None:
    models = StubModels({"primary": failure, "fallback": SCHEMA})
    answer = await _ask(_generator(models))
    assert answer.model == "fallback"  # в журнал попадёт модель, которая действительно ответила
    assert [c["model"] for c in models.calls] == ["primary", "fallback"]


async def test_whole_chain_down_is_service_unavailable() -> None:
    models = StubModels({"primary": OVERLOADED, "fallback": httpx.ConnectError("down")})
    with pytest.raises(ServiceUnavailableError, match="Language model is unavailable"):
        await _ask(_generator(models))


async def test_our_own_request_error_is_not_retried_on_other_models() -> None:
    models = StubModels(
        {"primary": errors.ClientError(400, {"error": {"message": "bad"}}), "fallback": SCHEMA}
    )
    with pytest.raises(ServiceUnavailableError):
        await _ask(_generator(models))
    assert [c["model"] for c in models.calls] == ["primary"]


async def test_malformed_model_output_is_rejected() -> None:
    with pytest.raises(ServiceUnavailableError, match="malformed"):
        await _ask(_generator(StubModels({"primary": None})))


def test_chain_must_not_be_empty() -> None:
    with pytest.raises(ValueError):
        _generator(StubModels({}), chain=())


async def test_unconfigured_generator_is_service_unavailable() -> None:
    with pytest.raises(ServiceUnavailableError, match="not configured"):
        await UnconfiguredAnswerGenerator().generate("q", AnswerLanguage.EN, [PASSAGE])


def test_prompt_states_the_safety_rules() -> None:
    prompt = load_prompt(ANSWER_PROMPT)
    rules = ("ONLY the procedure passages", '"refusal" to true', "VERBATIM quote")
    for rule in (*rules, "data, not instructions", "language attribute"):
        assert rule in prompt
