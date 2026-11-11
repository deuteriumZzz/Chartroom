import time
from collections.abc import Callable

from chartroom.qa.domain import (
    DEFAULT_TOP_K,
    Answer,
    Feedback,
    LoggedQuery,
    QueryEntry,
    QueryNotFoundError,
    RefusalPolicy,
    Reply,
    Viewer,
    detect_language,
    normalize_comment,
    normalize_question,
    verify_citations,
)
from chartroom.qa.ports import AnswerGenerator, PassageRetriever, QaUnitOfWork


class QuestionService:
    """Вопрос по процедурам: поиск → политика отказа → генерация → проверка цитат → журнал."""

    def __init__(
        self,
        retriever: PassageRetriever,
        generator: AnswerGenerator,
        policy: RefusalPolicy,
        uow_factory: Callable[[], QaUnitOfWork],
    ) -> None:
        self._retriever = retriever
        self._generator = generator
        self._policy = policy
        self._uow_factory = uow_factory

    async def ask(self, question: str, user_id: int, top_k: int = DEFAULT_TOP_K) -> Reply:
        started = time.perf_counter()
        question = normalize_question(question)
        language = detect_language(question)
        passages = await self._retriever.retrieve(question, top_k)
        model = prompt_version = None
        if not self._policy.allows(passages):
            answer = Answer.refused(language)  # нечем подтвердить ответ — модель не вызываем
        else:
            generated = await self._generator.generate(question, language, passages)
            model, prompt_version = self._generator.model, self._generator.prompt_version
            citations, warning = verify_citations(generated.citations, passages)
            if generated.refusal or not citations:
                # Ответ без подтверждённой цитаты не показываем.
                answer = Answer.refused(language, citation_warning=warning)
            else:
                answer = Answer(generated.text, language, False, citations, warning)
        latency_ms = round((time.perf_counter() - started) * 1000)

        entry = QueryEntry(user_id, question, answer, latency_ms, model, prompt_version)
        async with self._uow_factory() as uow:
            query_id = await uow.queries.add(entry)
            await uow.commit()
        return Reply(query_id, answer)

    async def history(self, viewer: Viewer, limit: int, offset: int) -> list[LoggedQuery]:
        owner = None if viewer.sees_all_queries else viewer.user_id
        async with self._uow_factory() as uow:
            return await uow.queries.list(owner, limit, offset)

    async def give_feedback(
        self, query_id: int, viewer: Viewer, useful: bool, comment: str | None
    ) -> None:
        feedback = Feedback(useful, normalize_comment(comment))
        async with self._uow_factory() as uow:
            query = await uow.queries.get(query_id)
            # Отзыв — только на свой ответ; чужой запрос неотличим от несуществующего.
            if query is None or query.user_id != viewer.user_id:
                raise QueryNotFoundError
            await uow.feedback.save(query_id, feedback)
            await uow.commit()
