from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from google import genai
from google.genai import errors, types

from chartroom.shared.errors import ServiceUnavailableError
from chartroom.shared.gemini import generate_with_fallback

CONFIG = types.GenerateContentConfig(temperature=0.0)
OVERLOADED = errors.ServerError(503, {"error": {"message": "high demand"}})


class StubModels:
    def __init__(self, outcomes: dict[str, Any]) -> None:
        self.calls: list[str] = []
        self._outcomes = outcomes

    async def generate_content(self, *, model: str, contents: str, config: Any) -> Any:
        self.calls.append(model)
        outcome = self._outcomes[model]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


async def _call(
    models: StubModels, chain: tuple[str, ...] = ("primary", "fallback")
) -> tuple[Any, str]:
    client = cast(genai.Client, SimpleNamespace(aio=SimpleNamespace(models=models)))
    return await generate_with_fallback(client, chain, "contents", CONFIG)


async def test_first_model_that_answers_wins() -> None:
    models = StubModels({"primary": "response"})
    assert await _call(models) == ("response", "primary")
    assert models.calls == ["primary"]


@pytest.mark.parametrize(
    "failure",
    [
        OVERLOADED,
        errors.ClientError(429, {"error": {"message": "quota"}}),
        httpx.ReadTimeout("slow"),
    ],
)
async def test_provider_failure_moves_to_the_next_model(failure: Exception) -> None:
    models = StubModels({"primary": failure, "fallback": "response"})
    assert await _call(models) == ("response", "fallback")


async def test_whole_chain_down_is_service_unavailable() -> None:
    models = StubModels({"primary": OVERLOADED, "fallback": httpx.ConnectError("down")})
    with pytest.raises(ServiceUnavailableError, match="Language model is unavailable"):
        await _call(models)


async def test_our_own_request_error_is_not_retried_on_other_models() -> None:
    models = StubModels(
        {"primary": errors.ClientError(400, {"error": {"message": "bad"}}), "fallback": "x"}
    )
    with pytest.raises(ServiceUnavailableError):
        await _call(models)
    assert models.calls == ["primary"]
