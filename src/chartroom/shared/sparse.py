"""Sparse-векторы для лексического поиска (BM25) — общий контракт индексации и поиска.

Документ и запрос обязаны кодироваться одной функцией разбиения на термины, иначе термины
не совпадут; поэтому код лежит в общем ядре, а не в одном из модулей.

Для документа — только частотная часть BM25 — насыщение и нормализация по длине. IDF считает Qdrant
по всей коллекции (sparse-вектор с modifier=IDF), поэтому он всегда актуален и не требует
пересчёта при добавлении документов.
"""

import re
import zlib
from collections import Counter, defaultdict
from dataclasses import dataclass

K1 = 1.2
B = 0.75
# Средняя длина фрагмента корпуса в словах (ADR-004: медиана ~35 токенов). Параметр настройки.
AVERAGE_LENGTH = 40

_WORD = re.compile(r"\w+")


@dataclass(frozen=True, slots=True)
class SparseVector:
    indices: tuple[int, ...]
    values: tuple[float, ...]


def term_id(term: str) -> int:
    # Стабильный хеш: встроенный hash() в Python меняется от запуска к запуску.
    return zlib.crc32(term.encode())


def bm25_vector(text: str) -> SparseVector:
    terms = [word.lower() for word in _WORD.findall(text)]
    length_norm = 1 - B + B * len(terms) / AVERAGE_LENGTH
    weights: defaultdict[int, float] = defaultdict(float)
    for term, frequency in Counter(terms).items():
        # Редкая коллизия crc32 складывает веса двух терминов — для поиска это допустимо.
        weights[term_id(term)] += frequency * (K1 + 1) / (frequency + K1 * length_norm)
    indices = tuple(sorted(weights))
    return SparseVector(indices, tuple(weights[i] for i in indices))


def bm25_query_vector(text: str) -> SparseVector:
    """Вектор запроса: каждый уникальный термин с весом 1, IDF домножает Qdrant."""
    indices = tuple(sorted({term_id(word.lower()) for word in _WORD.findall(text)}))
    return SparseVector(indices, tuple(1.0 for _ in indices))
