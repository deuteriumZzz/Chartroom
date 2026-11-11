import io
import zipfile

import docx
import pymupdf
import pytest

from chartroom.knowledge.adapters.parsers import (
    DocxParser,
    MarkdownParser,
    PdfParser,
    PlainTextParser,
)
from chartroom.knowledge.domain.models import Block, InvalidDocumentError


def test_markdown_builds_heading_path() -> None:
    content = (
        b"# Fire\n\nIntro.\n\n## 1. Purpose\nLine one\nLine two\n\n"
        b"## 2. Scope\n\n### 2.1 Ships\nAll ships.\n## 3. Records\nLog book.\n"
    )
    assert MarkdownParser().parse(content) == [
        Block("Intro.", ("Fire",)),
        Block("Line one\nLine two", ("Fire", "1. Purpose")),
        Block("All ships.", ("Fire", "2. Scope", "2.1 Ships")),
        Block("Log book.", ("Fire", "3. Records")),
    ]


def test_markdown_accepts_bom_and_rejects_binary() -> None:
    assert MarkdownParser().parse("﻿# T\ntext".encode()) == [Block("text", ("T",))]
    with pytest.raises(InvalidDocumentError):
        MarkdownParser().parse(b"\xff\xfe\x00binary")


def test_plain_text_splits_paragraphs_without_structure() -> None:
    content = b"First paragraph\nsame paragraph.\n\n\nSecond."
    assert PlainTextParser().parse(content) == [
        Block("First paragraph\nsame paragraph.", ()),
        Block("Second.", ()),
    ]


def _docx_bytes() -> bytes:
    document = docx.Document()
    document.add_heading("Fire Safety", level=0)
    document.add_heading("1. Purpose", level=1)
    document.add_paragraph("Defines crew actions.")
    document.add_heading("1.1 Alarm", level=2)
    document.add_paragraph("Sound the general alarm.")
    document.add_paragraph("")
    document.add_heading("2. Scope", level=1)
    document.add_paragraph("All crew members.")
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_docx_uses_title_and_heading_styles() -> None:
    assert DocxParser().parse(_docx_bytes()) == [
        Block("Defines crew actions.", ("Fire Safety", "1. Purpose")),
        Block("Sound the general alarm.", ("Fire Safety", "1. Purpose", "1.1 Alarm")),
        Block("All crew members.", ("Fire Safety", "2. Scope")),
    ]


def test_docx_rejects_archive_that_unpacks_too_large() -> None:
    with pytest.raises(InvalidDocumentError):
        DocxParser(max_uncompressed_bytes=1_000).parse(_docx_bytes())


def _zip_with(name: str, data: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, data)
    return buffer.getvalue()


@pytest.mark.parametrize(
    "content", [b"PK\x03\x04 not really a zip", _zip_with("hello.txt", b"not a word document")]
)
def test_docx_rejects_broken_files(content: bytes) -> None:
    with pytest.raises(InvalidDocumentError):
        DocxParser().parse(content)


def _pdf_bytes() -> bytes:
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Fire Safety", fontsize=20)
    page.insert_text((72, 110), "1. Purpose", fontsize=14)
    page.insert_text((72, 130), "This procedure defines crew actions in case of fire.", fontsize=11)
    page.insert_text((72, 145), "It applies to all vessels of the demo fleet.", fontsize=11)
    page = pdf.new_page()
    page.insert_text((72, 72), "2. Alarm", fontsize=14)
    page.insert_text((72, 92), "Sound the general alarm and report to the bridge.", fontsize=11)
    data: bytes = pdf.tobytes()
    return data


def test_pdf_detects_headings_by_font_size_and_keeps_pages() -> None:
    assert PdfParser().parse(_pdf_bytes()) == [
        Block(
            "This procedure defines crew actions in case of fire.\n"
            "It applies to all vessels of the demo fleet.",
            ("Fire Safety", "1. Purpose"),
            page=1,
        ),
        Block(
            "Sound the general alarm and report to the bridge.", ("Fire Safety", "2. Alarm"), page=2
        ),
    ]


def test_pdf_keeps_paragraphs_apart_and_skips_blank_lines() -> None:
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "First paragraph of body text.", fontsize=11)
    page.insert_text((72, 300), "Second paragraph far below.", fontsize=11)
    page.insert_text((72, 500), "     ", fontsize=11)
    assert PdfParser().parse(pdf.tobytes()) == [
        Block("First paragraph of body text.", (), page=1),
        Block("Second paragraph far below.", (), page=1),
    ]


def test_pdf_without_text_layer_gives_no_blocks() -> None:
    pdf = pymupdf.open()
    pdf.new_page()
    assert PdfParser().parse(pdf.tobytes()) == []


def test_pdf_rejects_corrupted_and_encrypted_files() -> None:
    encrypted = pymupdf.open(stream=_pdf_bytes(), filetype="pdf").tobytes(
        encryption=pymupdf.mupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="user"
    )
    for content in (b"%PDF-1.7 garbage", encrypted):
        with pytest.raises(InvalidDocumentError):
            PdfParser().parse(content)
