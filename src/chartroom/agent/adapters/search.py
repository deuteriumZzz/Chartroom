"""Мост к поиску модуля qa: фрагменты процедур в понятиях агента."""

from chartroom.agent.domain import Source
from chartroom.qa.ports import PassageRetriever


class QaProcedureSearch:
    def __init__(self, retriever: PassageRetriever) -> None:
        self._retriever = retriever

    async def search(self, query: str, top_k: int) -> list[Source]:
        passages = await self._retriever.retrieve(query, top_k)
        return [
            Source(0, p.document_id, p.version_id, p.title, p.section_path, p.page, p.text)
            for p in passages
        ]
