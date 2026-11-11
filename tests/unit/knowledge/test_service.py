import pytest

from chartroom.bootstrap import build_knowledge_service
from chartroom.knowledge.domain.models import (
    Block,
    DocumentFormat,
    EmptyDocumentError,
    UnsupportedFormatError,
)
from chartroom.knowledge.service import KnowledgeService
from tests.unit.knowledge.test_parsers import _docx_bytes, _pdf_bytes


class FakeParser:
    def __init__(self, blocks: list[Block]) -> None:
        self._blocks = blocks

    def parse(self, content: bytes) -> list[Block]:
        return self._blocks


def test_chunk_parses_by_detected_format_and_splits() -> None:
    service = KnowledgeService(
        {DocumentFormat.MARKDOWN: FakeParser([Block("Text.", ("Fire", "1. Purpose"))])}
    )
    [chunk] = service.chunk("fire.md", b"# ignored by fake")
    assert (chunk.section_path, chunk.text) == ("Fire / 1. Purpose", "Text.")


def test_document_without_text_is_rejected() -> None:
    service = KnowledgeService({DocumentFormat.TEXT: FakeParser([])})
    with pytest.raises(EmptyDocumentError):
        service.chunk("empty.txt", b"")


def test_unsupported_format_is_rejected_before_parsing() -> None:
    with pytest.raises(UnsupportedFormatError):
        KnowledgeService({}).chunk("setup.exe", b"MZ")


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("fire.md", b"# Fire\n## 1. Purpose\nText."),
        ("fire.txt", b"Text."),
        ("fire.docx", _docx_bytes()),
        ("fire.pdf", _pdf_bytes()),
    ],
)
def test_default_service_handles_every_format(filename: str, content: bytes) -> None:
    assert build_knowledge_service().chunk(filename, content)
