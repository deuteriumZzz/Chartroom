import pytest

from chartroom.knowledge.domain.models import (
    DocumentFormat,
    InvalidDocumentError,
    UnsupportedFormatError,
    detect_format,
)


@pytest.mark.parametrize(
    ("filename", "content", "expected"),
    [
        ("Fire.PDF", b"%PDF-1.7 ...", DocumentFormat.PDF),
        ("drill.docx", b"PK\x03\x04 ...", DocumentFormat.DOCX),
        ("notes.md", b"# Notes", DocumentFormat.MARKDOWN),
        ("notes.txt", b"plain", DocumentFormat.TEXT),
    ],
)
def test_detects_supported_formats(filename: str, content: bytes, expected: DocumentFormat) -> None:
    assert detect_format(filename, content) is expected


@pytest.mark.parametrize("filename", ["setup.exe", "no-extension", "archive.zip"])
def test_rejects_unsupported_extensions(filename: str) -> None:
    with pytest.raises(UnsupportedFormatError):
        detect_format(filename, b"anything")


@pytest.mark.parametrize(
    ("filename", "content"), [("fake.pdf", b"PK\x03\x04"), ("fake.docx", b"%PDF-")]
)
def test_rejects_content_that_does_not_match_extension(filename: str, content: bytes) -> None:
    with pytest.raises(InvalidDocumentError):
        detect_format(filename, content)
