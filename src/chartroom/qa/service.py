from chartroom.qa.domain import DEFAULT_TOP_K, Passage, normalize_question
from chartroom.qa.ports import PassageRetriever


class QuestionService:
    """Вопросы по процедурам: пока — поиск подтверждающих фрагментов (политика отказа
    и генерация ответа с цитатами — следующий шаг конвейера)."""

    def __init__(self, retriever: PassageRetriever) -> None:
        self._retriever = retriever

    async def ask(self, question: str, top_k: int = DEFAULT_TOP_K) -> list[Passage]:
        return await self._retriever.retrieve(normalize_question(question), top_k)
