from datetime import UTC, date, datetime

import pytest

from chartroom.knowledge.domain.indexing import chunk_point_id, embedding_input
from chartroom.knowledge.domain.models import (
    Chunk,
    DocumentVersion,
    DuplicateFileError,
    DuplicateVersionError,
    IndexingStatus,
    InvalidTitleError,
    ensure_new_version,
    normalize_title,
    should_activate,
)


def _version(
    label: str = "1", checksum: str = "aaa", issued_on: date = date(2026, 1, 1)
) -> DocumentVersion:
    return DocumentVersion(
        id=1,
        document_id=1,
        label=label,
        issued_on=issued_on,
        filename="fire.md",
        checksum=checksum,
        status=IndexingStatus.INDEXED,
        is_active=True,
        uploaded_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_normalize_title_collapses_whitespace() -> None:
    assert normalize_title("  Fire\t safety \n plan ") == "Fire safety plan"
    with pytest.raises(InvalidTitleError):
        normalize_title("   ")


def test_new_version_must_have_new_label_and_new_content() -> None:
    existing = [_version(label="3", checksum="aaa")]
    ensure_new_version(existing, label="4", checksum="bbb")
    with pytest.raises(DuplicateVersionError):
        ensure_new_version(existing, label="3", checksum="bbb")
    with pytest.raises(DuplicateFileError):
        ensure_new_version(existing, label="4", checksum="aaa")


@pytest.mark.parametrize(
    ("candidate", "active", "expected"),
    [
        (date(2026, 5, 1), None, True),
        (date(2026, 5, 1), date(2026, 1, 1), True),
        (date(2026, 5, 1), date(2026, 5, 1), True),
        (date(2026, 1, 1), date(2026, 5, 1), False),
    ],
)
def test_newest_issue_date_becomes_active(
    candidate: date, active: date | None, expected: bool
) -> None:
    current = _version(issued_on=active) if active else None
    assert should_activate(_version(issued_on=candidate), current) is expected


def test_point_ids_are_deterministic_and_distinct() -> None:
    assert chunk_point_id(7, 0) == chunk_point_id(7, 0)
    assert len({chunk_point_id(7, 0), chunk_point_id(7, 1), chunk_point_id(8, 0)}) == 3


@pytest.mark.parametrize(
    ("section_path", "expected_heading"),
    [
        ("Fire / 4.4 Engine room", "Fire / 4.4 Engine room"),
        ("4.4 Engine room", "Fire / 4.4 Engine room"),
        ("", "Fire"),
    ],
)
def test_embedding_input_adds_document_context(section_path: str, expected_heading: str) -> None:
    chunk = Chunk(
        index=0, text="Close the valves.", section_path=section_path, page=None, token_count=4
    )
    assert embedding_input("Fire", chunk) == f"{expected_heading}\n\nClose the valves."
