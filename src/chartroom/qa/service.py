from chartroom.qa.domain import (
    DEFAULT_TOP_K,
    Answer,
    RefusalPolicy,
    cited,
    detect_language,
    normalize_question,
)
from chartroom.qa.ports import AnswerGenerator, PassageRetriever


class QuestionService:
    """Вопрос по процедурам: поиск → политика отказа → генерация → цитаты."""

    def __init__(
        self, retriever: PassageRetriever, generator: AnswerGenerator, policy: RefusalPolicy
    ) -> None:
        self._retriever = retriever
        self._generator = generator
        self._policy = policy

    async def ask(self, question: str, top_k: int = DEFAULT_TOP_K) -> Answer:
        question = normalize_question(question)
        language = detect_language(question)
        passages = await self._retriever.retrieve(question, top_k)
        if not self._policy.allows(passages):
            return Answer.refused(language)  # нечем подтвердить ответ — модель не вызываем
        generated = await self._generator.generate(question, language, passages)
        citations = cited(generated, passages)
        if generated.refusal or not citations:
            return Answer.refused(language)  # ответ без подтверждённой цитаты не показываем
        return Answer(generated.text, language, refusal=False, citations=citations)
