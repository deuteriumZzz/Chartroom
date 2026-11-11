"""FR-6: ссылка допустима, только если указывает на переданный фрагмент и цитата в нём есть."""

from chartroom.qa.domain import Passage, RawCitation, verify_citations

FIRE = Passage(
    1,
    7,
    "Fire",
    "Fire / 4.4 Engine room",
    2,
    "Перед пуском закрывают быстрозапорные клапаны топлива, останавливают вентиляцию.",
    0.03,
    0.8,
)
ALARM = Passage(
    1,
    7,
    "Fire",
    "Fire / 4.2 Alarm",
    None,
    "**Signal:** seven short blasts and one long blast.",
    0.02,
    0.7,
)


def test_verbatim_quote_from_a_passed_passage_is_kept() -> None:
    citations, warning = verify_citations(
        [RawCitation(1, "закрывают быстрозапорные клапаны топлива")], [FIRE, ALARM]
    )
    assert warning is False
    [citation] = citations
    assert (citation.section_path, citation.page, citation.quote) == (
        "Fire / 4.4 Engine room",
        2,
        "закрывают быстрозапорные клапаны топлива",
    )


def test_punctuation_case_and_markdown_do_not_matter() -> None:
    citations, warning = verify_citations(
        [RawCitation(2, "Signal: Seven short blasts, and one long blast")], [FIRE, ALARM]
    )
    assert (len(citations), warning) == (1, False)


def test_reference_outside_the_context_is_removed_with_warning() -> None:
    citations, warning = verify_citations(
        [RawCitation(3, "anything"), RawCitation(0, "anything")], [FIRE, ALARM]
    )
    assert (citations, warning) == ((), True)


def test_quote_not_present_in_the_passage_is_removed_with_warning() -> None:
    raw = [
        RawCitation(1, "открывают клапаны топлива"),  # искажённая цитата
        RawCitation(2, "закрывают быстрозапорные клапаны"),  # верный текст, но из другого фрагмента
        RawCitation(1, "   "),  # пустая цитата ничего не подтверждает
        RawCitation(2, "seven short blasts"),
    ]
    citations, warning = verify_citations(raw, [FIRE, ALARM])
    assert warning is True
    assert [c.quote for c in citations] == ["seven short blasts"]


def test_duplicate_citations_are_kept_once() -> None:
    raw = [RawCitation(2, "seven short blasts"), RawCitation(2, "Seven  short blasts.")]
    citations, warning = verify_citations(raw, [FIRE, ALARM])
    assert (len(citations), warning) == (1, False)
