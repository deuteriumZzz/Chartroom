"""Sparse-вектор фрагмента для лексического поиска (BM25).

Здесь только частотная часть BM25 — насыщение и нормализация по длине. IDF считает Qdrant
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
