import pytest

from chartroom.knowledge.domain.chunking import chunk_blocks, count_tokens
from chartroom.knowledge.domain.models import Block


def test_count_tokens_counts_words_and_punctuation_runs() -> None:
    assert count_tokens("Пожар в МО!!!") == 4
    assert count_tokens("ROB 12.5 t") == 5


def test_each_section_becomes_its_own_chunk() -> None:
    blocks = [
        Block("Text a.", ("Fire", "1. Purpose")),
        Block("Text b.", ("Fire", "2. Scope")),
    ]
    chunks = chunk_blocks(blocks, max_tokens=100, overlap_tokens=10)
    assert [(c.index, c.section_path, c.text) for c in chunks] == [
        (0, "Fire / 1. Purpose", "Text a."),
        (1, "Fire / 2. Scope", "Text b."),
    ]


def test_long_section_is_split_by_sentences_with_overlap() -> None:
    text = "One two three. Four five six. Seven eight nine. Ten eleven twelve."
    chunks = chunk_blocks([Block(text, ("S",))], max_tokens=10, overlap_tokens=4)
    assert [c.text for c in chunks] == [
        "One two three. Four five six.",
        "Four five six. Seven eight nine.",
        "Seven eight nine. Ten eleven twelve.",
    ]
    assert all(c.token_count <= 10 for c in chunks)


def test_overlap_never_pushes_chunk_over_the_limit() -> None:
    text = " ".join(f"Sentence number {n}." for n in range(20))  # по 4 токена
    chunks = chunk_blocks([Block(text, ("S",))], max_tokens=10, overlap_tokens=8)
    assert all(c.token_count <= 10 for c in chunks)
    assert chunks[-1].text.endswith("Sentence number 19.")
    assert len({c.text for c in chunks}) == len(chunks)  # каждый чанк продвигается вперёд


def test_oversized_sentence_is_split_by_words() -> None:
    sentence = " ".join(f"w{n}" for n in range(25))
    chunks = chunk_blocks([Block(sentence, ("S",))], max_tokens=10, overlap_tokens=0)
    assert [c.token_count for c in chunks] == [10, 10, 5]


def test_chunk_takes_page_of_its_first_fragment() -> None:
    blocks = [Block("A one two.", ("S",), page=1), Block("B three four.", ("S",), page=2)]
    [chunk] = chunk_blocks(blocks, max_tokens=100, overlap_tokens=10)
    assert (chunk.page, chunk.text) == (1, "A one two.\nB three four.")


def test_line_breaks_inside_block_are_kept() -> None:
    [chunk] = chunk_blocks([Block("- item one\n- item two", ("S",))], max_tokens=100)
    assert chunk.text == "- item one\n- item two"


def test_blank_blocks_produce_no_chunks() -> None:
    assert chunk_blocks([Block("   \n ", ("S",))]) == []


def test_overlap_must_be_smaller_than_limit() -> None:
    with pytest.raises(ValueError):
        chunk_blocks([Block("text", ())], max_tokens=10, overlap_tokens=10)
