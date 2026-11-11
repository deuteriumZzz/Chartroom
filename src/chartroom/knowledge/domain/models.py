"""Документы и их фрагменты. Чистые типы и правила — без библиотек разбора."""

from dataclasses import dataclass
from enum import StrEnum

from chartroom.shared.errors import InvalidInputError


class DocumentFormat(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    MARKDOWN = "md"
    TEXT = "txt"


# Бинарные форматы проверяем по сигнатуре: расширение задаёт пользователь, содержимое — нет.
_SIGNATURES = {DocumentFormat.PDF: b"%PDF-", DocumentFormat.DOCX: b"PK\x03\x04"}


class UnsupportedFormatError(InvalidInputError):
    message = "Supported formats: " + ", ".join(DocumentFormat)


class InvalidDocumentError(InvalidInputError):
    message = "File is corrupted or does not match its format"


class EmptyDocumentError(InvalidInputError):
    message = "Document has no extractable text"


@dataclass(frozen=True, slots=True)
class Block:
    """Абзац документа и его место в структуре: путь заголовков и страница (если есть)."""

    text: str
    heading_path: tuple[str, ...]
    page: int | None = None


@dataclass(frozen=True, slots=True)
class Chunk:
    """Фрагмент для поиска. Всегда лежит внутри одного раздела, поэтому ссылка точна."""

    index: int
    text: str
    section_path: str
    page: int | None
    token_count: int


def detect_format(filename: str, content: bytes) -> DocumentFormat:
    _, dot, extension = filename.rpartition(".")
    try:
        document_format = DocumentFormat(extension.lower()) if dot else None
    except ValueError:
        document_format = None
    if document_format is None:
        raise UnsupportedFormatError
    signature = _SIGNATURES.get(document_format)
    if signature is not None and not content.startswith(signature):
        raise InvalidDocumentError
    return document_format
