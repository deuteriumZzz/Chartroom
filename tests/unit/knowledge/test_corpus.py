"""Регрессия синтетического корпуса: правки автора не должны ломать структуру и плашку «демо»."""

import pathlib

import pytest

from chartroom.bootstrap import build_knowledge_service
from chartroom.knowledge.domain.chunking import MAX_CHUNK_TOKENS

CORPUS = pathlib.Path(__file__).resolve().parents[3] / "data" / "corpus"
DOCUMENTS = sorted(CORPUS.glob("*/*.md"))
DISCLAIMER = {
    "ru": "Синтетический документ для демонстрации Chartroom",
    "en": "Synthetic document for the Chartroom demo",
}


def _cyrillic_share(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    return sum("Ѐ" <= c <= "ӿ" for c in letters) / len(letters)


def test_corpus_has_10_to_15_documents_in_both_languages() -> None:
    assert 10 <= len(DOCUMENTS) <= 15
    assert {path.parent.name for path in DOCUMENTS} == {"ru", "en"}


@pytest.mark.parametrize("path", DOCUMENTS, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_corpus_document_is_well_formed(path: pathlib.Path) -> None:
    text = path.read_text(encoding="utf-8")
    language = path.parent.name
    # Ни один документ не должен выглядеть как действующая процедура.
    assert DISCLAIMER[language] in text
    share = _cyrillic_share(text)
    assert share > 0.6 if language == "ru" else share < 0.01

    chunks = build_knowledge_service().chunk(path.name, path.read_bytes())
    assert len({chunk.section_path for chunk in chunks}) >= 4
    assert all(chunk.token_count <= MAX_CHUNK_TOKENS for chunk in chunks)
