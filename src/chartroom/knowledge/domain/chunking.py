"""Нарезка документа на фрагменты для поиска.

Правила:
- фрагмент не пересекает границу раздела: ссылка на раздел всегда точная;
- длинный раздел режется по предложениям, соседние фрагменты перекрываются целыми
  предложениями (до `overlap_tokens`), чтобы мысль на стыке не терялась;
- фрагмент никогда не длиннее `max_tokens`, в том числе с перекрытием.

Токены считаются приближённо (слова и группы знаков препинания). Точный токенизатор зависит
от модели эмбеддингов; размеры — параметр настройки, их проверяет eval (день 9).
"""

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from itertools import groupby, pairwise

from chartroom.knowledge.domain.models import Block, Chunk

MAX_CHUNK_TOKENS = 500
CHUNK_OVERLAP_TOKENS = 50

_TOKEN = re.compile(r"\w+|[^\w\s]+")
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


@dataclass(frozen=True, slots=True)
class _Unit:
    text: str
    page: int | None
    line: int  # номер строки внутри раздела: разные строки склеиваются переводом строки
    tokens: int


def count_tokens(text: str) -> int:
    return len(_TOKEN.findall(text))


def chunk_blocks(
    blocks: Sequence[Block],
    max_tokens: int = MAX_CHUNK_TOKENS,
    overlap_tokens: int = CHUNK_OVERLAP_TOKENS,
) -> list[Chunk]:
    if not 0 <= overlap_tokens < max_tokens:
        raise ValueError("overlap_tokens must be in [0, max_tokens)")
    chunks: list[Chunk] = []
    for path, section in groupby(blocks, key=lambda block: block.heading_path):
        units = list(_units(section, max_tokens))
        for window in _windows(units, max_tokens, overlap_tokens):
            chunks.append(
                Chunk(
                    index=len(chunks),
                    text=_join(window),
                    section_path=" / ".join(path),
                    page=window[0].page,
                    token_count=sum(unit.tokens for unit in window),
                )
            )
    return chunks


def _units(section: Iterator[Block], max_tokens: int) -> Iterator[_Unit]:
    line_no = 0
    for block in section:
        for line in block.text.splitlines():
            line_no += 1
            for sentence in _SENTENCE_END.split(line.strip()):
                if sentence:
                    for piece in _split_oversized(sentence, max_tokens):
                        yield _Unit(piece, block.page, line_no, count_tokens(piece))


def _split_oversized(sentence: str, max_tokens: int) -> list[str]:
    if count_tokens(sentence) <= max_tokens:
        return [sentence]
    pieces: list[str] = []
    words: list[str] = []
    tokens = 0
    for word in sentence.split():
        word_tokens = count_tokens(word)
        if words and tokens + word_tokens > max_tokens:
            pieces.append(" ".join(words))
            words, tokens = [], 0
        words.append(word)
        tokens += word_tokens
    pieces.append(" ".join(words))
    return pieces


def _windows(units: list[_Unit], max_tokens: int, overlap_tokens: int) -> Iterator[list[_Unit]]:
    window: list[_Unit] = []
    has_new_units = False
    for unit in units:
        if has_new_units and _size(window) + unit.tokens > max_tokens:
            yield window
            window = _tail(window, overlap_tokens)
            has_new_units = False
        while window and _size(window) + unit.tokens > max_tokens:
            window.pop(0)  # перекрытие не должно раздувать фрагмент сверх лимита
        window.append(unit)
        has_new_units = True
    if has_new_units:
        yield window


def _tail(window: list[_Unit], overlap_tokens: int) -> list[_Unit]:
    tail: list[_Unit] = []
    for unit in reversed(window):
        if _size(tail) + unit.tokens > overlap_tokens:
            break
        tail.insert(0, unit)
    return tail


def _size(units: list[_Unit]) -> int:
    return sum(unit.tokens for unit in units)


def _join(window: list[_Unit]) -> str:
    parts = [window[0].text]
    for previous, current in pairwise(window):
        parts.append(("\n" if current.line != previous.line else " ") + current.text)
    return "".join(parts)
