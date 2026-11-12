import pytest

from chartroom.agent.domain import (
    DATA_TOOLS,
    REFUSAL_TEXT,
    TOOLS,
    InvalidAgentQuestionError,
    InvalidSubmissionError,
    Source,
    finalize,
    normalize_question,
)
from chartroom.shared.language import Language
from chartroom.shared.schema import check_schema

FIRE = Source(
    1, 1, 7, "Fire", "Fire / 4.4", None, "Close the fuel valves and stop the ventilation."
)


def test_data_tool_arguments_use_the_supported_schema_subset() -> None:
    for tool in DATA_TOOLS:
        check_schema(tool.parameters)  # иначе проверка аргументов молча пропускала бы правила
    assert [t.name for t in TOOLS][-1] == "submit_answer"
    assert len({t.name for t in TOOLS}) == len(TOOLS)


def test_verified_citation_is_kept() -> None:
    answer = finalize(
        {
            "answer": " Close the valves. ",
            "refusal": False,
            "citations": [{"passage": 1, "quote": "close the FUEL valves"}],
        },
        [FIRE],
        Language.EN,
        steps=2,
    )
    assert (answer.text, answer.refusal, answer.citation_warning, answer.steps) == (
        "Close the valves.",
        False,
        False,
        2,
    )
    assert [(c.section_path, c.quote) for c in answer.citations] == [
        ("Fire / 4.4", "close the FUEL valves")
    ]


@pytest.mark.parametrize(
    "citation",
    [
        {
            "passage": 2,
            "quote": "Close the fuel valves",
        },  # фрагмента с таким номером в запросе не было
        {"passage": 1, "quote": "Open the fuel valves"},  # искажённая цитата
        {"passage": "1", "quote": "Close the fuel valves"},
        "not an object",
    ],
)
def test_unverifiable_citation_is_dropped_with_warning(citation: object) -> None:
    answer = finalize(
        {"answer": "A.", "refusal": False, "citations": [citation]}, [FIRE], Language.EN, 1
    )
    assert (answer.citations, answer.citation_warning) == ((), True)


def test_duplicate_citations_are_kept_once() -> None:
    quotes = [
        {"passage": 1, "quote": "stop the ventilation"},
        {"passage": 1, "quote": "Stop the ventilation."},
    ]
    answer = finalize(
        {"answer": "A.", "refusal": False, "citations": quotes}, [FIRE], Language.EN, 1
    )
    assert len(answer.citations) == 1


@pytest.mark.parametrize(
    "args", [{"answer": "", "refusal": False}, {"answer": "x", "refusal": True}]
)
def test_refusal_or_empty_answer_becomes_localized_refusal(args: dict[str, object]) -> None:
    answer = finalize(args, [FIRE], Language.RU, 3)
    assert (answer.refusal, answer.text) == (True, REFUSAL_TEXT[Language.RU])


@pytest.mark.parametrize(
    "args", [{}, {"answer": 1, "refusal": False}, {"answer": "x", "refusal": "no"}]
)
def test_malformed_submission_is_an_error(args: dict[str, object]) -> None:
    with pytest.raises(InvalidSubmissionError):
        finalize(args, [], Language.EN, 1)


def test_question_is_normalized_and_bounded() -> None:
    assert normalize_question("  Какие   отчёты? ") == "Какие отчёты?"
    for bad in ["  ", "x" * 1001]:
        with pytest.raises(InvalidAgentQuestionError):
            normalize_question(bad)
