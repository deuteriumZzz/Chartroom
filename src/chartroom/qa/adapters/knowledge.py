"""Мост к модулю knowledge: его поиск в понятиях модуля qa (anti-corruption layer).

Единственное место, где qa знает о knowledge; связь явно разрешена в контрактах import-linter.
"""

from chartroom.knowledge.service import ChunkRetriever
from chartroom.qa.domain import Passage


class KnowledgePassageRetriever:
    def __init__(self, retriever: ChunkRetriever) -> None:
        self._retriever = retriever

    async def retrieve(self, question: str, limit: int) -> list[Passage]:
        return [
            Passage(
                document_id=chunk.document_id,
                version_id=chunk.version_id,
                title=chunk.title,
                section_path=chunk.section_path,
                page=chunk.page,
                text=chunk.text,
                score=chunk.score,
                similarity=chunk.similarity,
            )
            for chunk in await self._retriever.retrieve(question, limit)
        ]
