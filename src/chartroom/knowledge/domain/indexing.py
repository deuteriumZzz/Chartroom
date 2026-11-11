"""Правила индексации, не зависящие от конкретного векторного хранилища."""

import uuid
from dataclasses import dataclass

from chartroom.knowledge.domain.models import Chunk, Language
from chartroom.shared.sparse import SparseVector

_POINT_NAMESPACE = uuid.UUID("6d1f3c2a-8a51-4f5e-9a57-2b0c6f1e9d40")


def chunk_point_id(version_id: int, chunk_index: int) -> uuid.UUID:
    """Детерминированный id точки: повтор индексации перезаписывает точки, а не дублирует их."""
    return uuid.uuid5(_POINT_NAMESPACE, f"{version_id}:{chunk_index}")


def embedding_input(title: str, chunk: Chunk) -> str:
    """Текст для эмбеддинга: название документа и путь раздела перед текстом фрагмента.

    Короткий фрагмент без контекста («Закрыть клапаны.») плохо находится по вопросу о пожаре.
    """
    path = chunk.section_path
    heading = path if path.startswith(title) else " / ".join(part for part in (title, path) if part)
    return f"{heading}\n\n{chunk.text}"


@dataclass(frozen=True, slots=True)
class IndexedChunk:
    """Фрагмент, готовый к записи в индекс: векторы и метаданные для цитаты."""

    point_id: uuid.UUID
    document_id: int
    version_id: int
    title: str
    language: Language
    chunk: Chunk
    dense: tuple[float, ...]
    sparse: SparseVector


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """Найденный фрагмент с данными для цитаты: документ, версия, раздел, страница."""

    document_id: int
    version_id: int
    title: str
    language: Language
    section_path: str
    page: int | None
    chunk_index: int
    text: str
    score: float
