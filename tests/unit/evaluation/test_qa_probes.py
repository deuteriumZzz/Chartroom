from chartroom.evaluation.adapters.qa import QaAnswerProbe, QaRetrievalProbe
from chartroom.evaluation.domain import Hit
from chartroom.qa.domain import GeneratedAnswer, Passage, RawCitation, RefusalPolicy
from chartroom.qa.service import QuestionService
from tests.fakes import InMemoryQaUnitOfWork, QaStore, ScriptedGenerator, StaticPassageRetriever

PASSAGE = Passage(1, 7, "Fire", "Fire / 4.4", None, "Close the fuel valves.", 0.03, 0.81)


async def test_retrieval_probe_reports_where_passages_are_and_how_close() -> None:
    probe = QaRetrievalProbe(StaticPassageRetriever([PASSAGE]))
    assert await probe.hits("fuel?", 5) == [Hit("Fire", "Fire / 4.4", 0.81)]


async def test_answer_probe_asks_the_real_question_service() -> None:
    answer = GeneratedAnswer("Close.", (RawCitation(1, "Close the fuel valves"),), False, "m")
    store = QaStore()
    service = QuestionService(
        StaticPassageRetriever([PASSAGE]),
        ScriptedGenerator(answer),
        RefusalPolicy(0.5),
        lambda: InMemoryQaUnitOfWork(store),
    )
    outcome = await QaAnswerProbe(service, user_id=42).outcome("fuel?")
    assert (outcome.refusal, outcome.cited, outcome.citation_warning) == (
        False,
        (("Fire", "Fire / 4.4"),),
        False,
    )
    assert outcome.latency_ms >= 0
    assert [q.user_id for q in store.queries.values()] == [42]  # журнал знает, кто спрашивал
