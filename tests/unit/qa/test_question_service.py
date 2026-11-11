import pytest

from chartroom.qa.domain import (
    MAX_QUESTION_LENGTH,
    InvalidQuestionError,
    Passage,
    normalize_question,
)
from chartroom.qa.service import QuestionService
from tests.fakes import StaticPassageRetriever

PASSAGE = Passage(1, 7, "Fire", "Fire / 4.4 Engine room", None, "Close the fuel valves.", 0.9, 0.82)


def test_question_is_normalized_and_bounded() -> None:
    assert normalize_question("  Что   делать\nпри пожаре? ") == "Что делать при пожаре?"
    for bad in ["   ", "x" * (MAX_QUESTION_LENGTH + 1)]:
        with pytest.raises(InvalidQuestionError):
            normalize_question(bad)


async def test_ask_retrieves_passages_for_normalized_question() -> None:
    retriever = StaticPassageRetriever([PASSAGE])
    assert await QuestionService(retriever).ask("  fuel   valves ", top_k=3) == [PASSAGE]
    assert retriever.calls == [("fuel valves", 3)]


async def test_invalid_question_never_reaches_search() -> None:
    retriever = StaticPassageRetriever([PASSAGE])
    with pytest.raises(InvalidQuestionError):
        await QuestionService(retriever).ask(" ")
    assert retriever.calls == []
