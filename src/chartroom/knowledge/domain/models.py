"""Документы и их фрагменты. Чистые типы и правила — без библиотек разбора."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from chartroom.shared.errors import ConflictError, InvalidInputError, NotFoundError


class DocumentFormat(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    MARKDOWN = "md"
    TEXT = "txt"


class Language(StrEnum):
    RU = "ru"
    EN = "en"


class IndexingStatus(StrEnum):
    PENDING = "pending"  # загружен, ждёт worker
    INDEXING = "indexing"
    INDEXED = "indexed"
    FAILED = "failed"


MAX_UPLOAD_BYTES = 20 * 1024 * 1024

# Бинарные форматы проверяем по сигнатуре: расширение задаёт пользователь, содержимое — нет.
_SIGNATURES = {DocumentFormat.PDF: b"%PDF-", DocumentFormat.DOCX: b"PK\x03\x04"}


class UnsupportedFormatError(InvalidInputError):
    message = "Supported formats: " + ", ".join(DocumentFormat)


class InvalidDocumentError(InvalidInputError):
    message = "File is corrupted or does not match its format"


class EmptyDocumentError(InvalidInputError):
    message = "Document has no extractable text"


class FileTooLargeError(InvalidInputError):
    message = f"File is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB"


class InvalidTitleError(InvalidInputError):
    message = "Document title is required"


class InvalidVersionLabelError(InvalidInputError):
    message = "Version label is required"


class DocumentNotFoundError(NotFoundError):
    message = "Document not found"


class DuplicateVersionError(ConflictError):
    message = "This version label already exists for the document"


class DuplicateFileError(ConflictError):
    message = "This file is already uploaded for the document"


class DocumentAlreadyExistsError(ConflictError):
    # Две одновременные загрузки нового документа с одним названием: вторая получает конфликт.
    message = "Document was created by a concurrent upload, retry"


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


@dataclass(frozen=True, slots=True)
class Document:
    id: int
    title: str
    language: Language


@dataclass(frozen=True, slots=True)
class DocumentVersion:
    id: int
    document_id: int
    label: str
    issued_on: date
    filename: str
    checksum: str
    status: IndexingStatus
    is_active: bool
    uploaded_at: datetime
    error: str | None = None


@dataclass(frozen=True, slots=True)
class DocumentUpload:
    title: str
    language: Language
    label: str
    issued_on: date
    filename: str
    content: bytes


@dataclass(frozen=True, slots=True)
class DocumentOverview:
    document: Document
    versions: list[DocumentVersion]


def normalize_title(raw: str) -> str:
    title = " ".join(raw.split())
    if not title:
        raise InvalidTitleError
    return title


def safe_filename(raw: str) -> str:
    """Только последний компонент пути: «../../etc/fire.md» становится «fire.md»."""
    return raw.replace("\\", "/").rsplit("/", 1)[-1]


def normalize_label(raw: str) -> str:
    label = raw.strip()
    if not label:
        raise InvalidVersionLabelError
    return label


def ensure_new_version(existing: Sequence[DocumentVersion], label: str, checksum: str) -> None:
    if any(version.label == label for version in existing):
        raise DuplicateVersionError
    if any(version.checksum == checksum for version in existing):
        raise DuplicateFileError


def should_activate(candidate: DocumentVersion, active: DocumentVersion | None) -> bool:
    """Активна редакция с самой поздней датой выпуска: старая, загруженная позже, её не вытеснит."""
    return active is None or candidate.issued_on >= active.issued_on
