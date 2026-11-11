import pytest

from chartroom.qa.domain import (
    REFUSAL_TEXT,
    Answer,
    AnswerLanguage,
    Feedback,
    GeneratedAnswer,
    InvalidFeedbackError,
    InvalidQuestionError,
    Passage,
    QueryNotFoundError,
    RawCitation,
    RefusalPolicy,
    Viewer,
)
from chartroom.qa.service import QuestionService
from chartroom.shared.errors import ServiceUnavailableError
from tests.fakes import InMemoryQaUnitOfWork, QaStore, ScriptedGenerator, StaticPassageRetriever

POLICY = RefusalPolicy(min_similarity=0.6)
VALVES = Passage(1, 7, "Fire", "Fire / 4.4 Engine room", None, "Close the fuel valves.", 0.03, 0.82)
ALARM = Passage(1, 7, "Fire", "Fire / 4.2 Alarm", None, "Sound the general alarm.", 0.02, 0.64)
GOOD = GeneratedAnswer("Close the fuel valves.", (RawCitation(1, "Close the fuel valves"),), False)


OFFICER = 7


class Asker:
    """Сервис с фейками: ask() возвращает ответ, журнал доступен для проверок."""

    def __init__(self, passages: list[Passage], answer: GeneratedAnswer = GOOD) -> None:
        self.retriever, self.generator = StaticPassageRetriever(passages), ScriptedGenerator(answer)
        self.store = QaStore()
        self.service = QuestionService(
            self.retriever, self.generator, POLICY, lambda: InMemoryQaUnitOfWork(self.store)
        )

    async def ask(self, question: str, top_k: int = 5) -> Answer:
        return (await self.service.ask(question, OFFICER, top_k)).answer


def _service(
    passages: list[Passage], answer: GeneratedAnswer = GOOD
) -> tuple[Asker, StaticPassageRetriever, ScriptedGenerator]:
    asker = Asker(passages, answer)
    return asker, asker.retriever, asker.generator


async def test_answer_is_generated_from_passages_with_verified_citations() -> None:
    service, retriever, generator = _service([VALVES, ALARM])
    answer = await service.ask("  What to do with   fuel valves? ", top_k=2)
    assert (answer.text, answer.refusal, answer.language, answer.citation_warning) == (
        "Close the fuel valves.",
        False,
        AnswerLanguage.EN,
        False,
    )
    assert [(c.section_path, c.quote) for c in answer.citations] == [
        ("Fire / 4.4 Engine room", "Close the fuel valves")
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
    ("generated", "warning"),
    [
        (GeneratedAnswer("", (), refusal=True), False),
        (GeneratedAnswer("Unsupported claim.", (), refusal=False), False),
        (GeneratedAnswer("Made up.", (RawCitation(9, "anything"),), refusal=False), True),
        (
            GeneratedAnswer("Misquoted.", (RawCitation(1, "Open the fuel valves"),), refusal=False),
            True,
        ),
    ],
)
async def test_model_refusal_or_unsupported_answer_becomes_refusal(
    generated: GeneratedAnswer, warning: bool
) -> None:
    service, _, _ = _service([VALVES], generated)
    answer = await service.ask("fuel valves?")
    assert (answer.refusal, answer.text, answer.citation_warning) == (
        True,
        REFUSAL_TEXT[AnswerLanguage.EN],
        warning,
    )


async def test_invalid_citation_is_dropped_and_flagged_but_valid_ones_stay() -> None:
    citations = (
        RawCitation(1, "Close the fuel valves"),
        RawCitation(2, "Sound the general alarm"),
        RawCitation(5, "ghost"),
    )
    service, _, _ = _service([VALVES, ALARM], GeneratedAnswer("Valves, alarm.", citations, False))
    answer = await service.ask("fire?")
    assert (answer.refusal, answer.citation_warning) == (False, True)
    assert [c.quote for c in answer.citations] == [
        "Close the fuel valves",
        "Sound the general alarm",
    ]


async def test_invalid_question_never_reaches_search() -> None:
    service, retriever, _ = _service([VALVES])
    with pytest.raises(InvalidQuestionError):
        await service.ask(" ")
    assert retriever.calls == []


async def test_model_outage_propagates() -> None:
    class DownGenerator(ScriptedGenerator):
        async def generate(self, *args: object, **kwargs: object) -> GeneratedAnswer:
            raise ServiceUnavailableError("Language model is unavailable")

    service = QuestionService(
        StaticPassageRetriever([VALVES]),
        DownGenerator(GOOD),
        POLICY,
        lambda: InMemoryQaUnitOfWork(QaStore()),
    )
    with pytest.raises(ServiceUnavailableError):
        await service.ask("fuel valves?", OFFICER)


async def test_every_answer_is_logged_with_model_prompt_and_latency() -> None:
    asker = Asker([VALVES])
    reply = await asker.service.ask("fuel valves?", OFFICER)
    refused = await Asker([]).service.ask("fuel valves?", OFFICER)
    [logged] = asker.store.queries.values()
    assert (logged.id, logged.user_id, logged.question, logged.answer) == (
        reply.query_id,
        OFFICER,
        "fuel valves?",
        reply.answer,
    )
    assert (logged.model, logged.prompt_version, logged.latency_ms >= 0) == (
        "scripted-model",
        "test.v1",
        True,
    )
    assert refused.answer.refusal  # отказ без вызова модели — тоже в журнале, без модели и промпта


async def test_refusal_without_model_is_logged_without_model() -> None:
    asker = Asker([])
    await asker.service.ask("fuel valves?", OFFICER)
    [logged] = asker.store.queries.values()
    assert (logged.answer.refusal, logged.model, logged.prompt_version) == (True, None, None)


async def test_officer_sees_own_history_captain_sees_everyone() -> None:
    asker = Asker([VALVES])
    for user_id in (OFFICER, 8, OFFICER):
        await asker.service.ask("fuel valves?", user_id)
    own = await asker.service.history(Viewer(OFFICER, sees_all_queries=False), limit=10, offset=0)
    everyone = await asker.service.history(Viewer(99, sees_all_queries=True), limit=2, offset=1)
    assert [(q.id, q.user_id) for q in own] == [(3, OFFICER), (1, OFFICER)]
    assert [q.id for q in everyone] == [2, 1]


async def test_feedback_is_saved_and_replaced_on_own_query() -> None:
    asker = Asker([VALVES])
    reply = await asker.service.ask("fuel valves?", OFFICER)
    me = Viewer(OFFICER, sees_all_queries=False)
    await asker.service.give_feedback(reply.query_id, me, useful=False, comment="  missing step  ")
    await asker.service.give_feedback(reply.query_id, me, useful=True, comment=" ")
    assert asker.store.queries[reply.query_id].feedback == Feedback(useful=True, comment=None)


@pytest.mark.parametrize("viewer", [Viewer(8, False), Viewer(99, True)])
async def test_feedback_on_someone_elses_query_looks_like_missing(viewer: Viewer) -> None:
    asker = Asker([VALVES])
    reply = await asker.service.ask("fuel valves?", OFFICER)
    for query_id in (reply.query_id, 404):
        with pytest.raises(QueryNotFoundError):
            await asker.service.give_feedback(query_id, viewer, useful=True, comment=None)


async def test_too_long_feedback_comment_is_rejected() -> None:
    asker = Asker([VALVES])
    reply = await asker.service.ask("fuel valves?", OFFICER)
    with pytest.raises(InvalidFeedbackError):
        await asker.service.give_feedback(reply.query_id, Viewer(OFFICER, False), True, "x" * 1001)
