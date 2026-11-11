import pytest

from chartroom.qa.domain import (
    REFUSAL_TEXT,
    AnswerLanguage,
    GeneratedAnswer,
    InvalidQuestionError,
    Passage,
    RefusalPolicy,
)
from chartroom.qa.service import QuestionService
from chartroom.shared.errors import ServiceUnavailableError
from tests.fakes import ScriptedGenerator, StaticPassageRetriever

POLICY = RefusalPolicy(min_similarity=0.6)
VALVES = Passage(1, 7, "Fire", "Fire / 4.4 Engine room", None, "Close the fuel valves.", 0.03, 0.82)
ALARM = Passage(1, 7, "Fire", "Fire / 4.2 Alarm", None, "Sound the general alarm.", 0.02, 0.64)
GOOD = GeneratedAnswer("Close the fuel valves [1].", citations=(1,), refusal=False)


def _service(
    passages: list[Passage], answer: GeneratedAnswer = GOOD
) -> tuple[QuestionService, StaticPassageRetriever, ScriptedGenerator]:
    retriever, generator = StaticPassageRetriever(passages), ScriptedGenerator(answer)
    return QuestionService(retriever, generator, POLICY), retriever, generator


async def test_answer_is_generated_from_passages_with_citations() -> None:
    service, retriever, generator = _service([VALVES, ALARM])
    answer = await service.ask("  What to do with   fuel valves? ", top_k=2)
    assert (answer.text, answer.refusal, answer.language) == (
        "Close the fuel valves [1].",
        False,
        AnswerLanguage.EN,
    )
    assert [(c.section_path, c.quote) for c in answer.citations] == [
        ("Fire / 4.4 Engine room", "Close the fuel valves.")
    ]
    assert retriever.calls == [("What to do with fuel valves?", 2)]
    assert generator.calls == [("What to do with fuel valves?", AnswerLanguage.EN, [VALVES, ALARM])]


@pytest.mark.parametrize(
    "passages",
    [[], [Passage(1, 7, "Fire", "Fire / 1", None, "Unrelated.", 0.03, 0.41)]],
)
async def test_refusal_without_calling_the_model(passages: list[Passage]) -> None:
    service, _, generator = _service(passages)
    answer = await service.ask("Как часто проводится учение по оставлению судна?")
    assert (answer.refusal, answer.text, answer.citations) == (
        True,
        REFUSAL_TEXT[AnswerLanguage.RU],
        (),
    )
    assert generator.calls == []


@pytest.mark.parametrize(
    "generated",
    [
        GeneratedAnswer("", citations=(), refusal=True),
        GeneratedAnswer("Unsupported claim.", citations=(), refusal=False),
        GeneratedAnswer("Made-up source.", citations=(9,), refusal=False),
    ],
)
async def test_model_refusal_or_unsupported_answer_becomes_refusal(
    generated: GeneratedAnswer,
) -> None:
    service, _, _ = _service([VALVES], generated)
    answer = await service.ask("fuel valves?")
    assert (answer.refusal, answer.text) == (True, REFUSAL_TEXT[AnswerLanguage.EN])


async def test_invalid_question_never_reaches_search() -> None:
    service, retriever, _ = _service([VALVES])
    with pytest.raises(InvalidQuestionError):
        await service.ask(" ")
    assert retriever.calls == []


async def test_model_outage_propagates() -> None:
    class DownGenerator(ScriptedGenerator):
        async def generate(self, *args: object, **kwargs: object) -> GeneratedAnswer:
            raise ServiceUnavailableError("Language model is unavailable")

    service = QuestionService(StaticPassageRetriever([VALVES]), DownGenerator(GOOD), POLICY)
    with pytest.raises(ServiceUnavailableError):
        await service.ask("fuel valves?")
