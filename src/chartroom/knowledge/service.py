from collections.abc import Mapping

from chartroom.knowledge.domain.chunking import chunk_blocks
from chartroom.knowledge.domain.models import (
    Chunk,
    DocumentFormat,
    EmptyDocumentError,
    detect_format,
)
from chartroom.knowledge.ports import DocumentParser


class KnowledgeService:
    """Сценарии модуля knowledge: подготовка документа к индексации."""

    def __init__(self, parsers: Mapping[DocumentFormat, DocumentParser]) -> None:
        self._parsers = parsers

    def chunk(self, filename: str, content: bytes) -> list[Chunk]:
        document_format = detect_format(filename, content)
        chunks = chunk_blocks(self._parsers[document_format].parse(content))
        if not chunks:
            raise EmptyDocumentError
        return chunks
