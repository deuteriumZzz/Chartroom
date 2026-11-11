"""Разбор файлов в блоки с путём заголовков. Каждый класс реализует порт DocumentParser."""

import io
import re
import zipfile
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass

import docx
import pymupdf

from chartroom.knowledge.domain.models import Block, InvalidDocumentError

MAX_DOCX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
_MARKDOWN_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_DOCX_HEADING_STYLE = re.compile(r"^Heading (\d)$")
_PDF_HEADING_SCALE = 1.15  # строка PDF — заголовок, если шрифт на 15% крупнее основного текста


class _HeadingPath:
    """Текущий путь заголовков: заголовок уровня N закрывает все открытые уровни ≥ N."""

    def __init__(self) -> None:
        self._stack: list[tuple[int, str]] = []

    def enter(self, level: int, title: str) -> None:
        while self._stack and self._stack[-1][0] >= level:
            self._stack.pop()
        self._stack.append((level, title))

    @property
    def current(self) -> tuple[str, ...]:
        return tuple(title for _, title in self._stack)


def _decode(content: bytes) -> str:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise InvalidDocumentError from e


class MarkdownParser:
    def parse(self, content: bytes) -> list[Block]:
        headings = _HeadingPath()
        blocks: list[Block] = []
        paragraph: list[str] = []

        def flush() -> None:
            if paragraph:
                blocks.append(Block("\n".join(paragraph), headings.current))
                paragraph.clear()

        for line in _decode(content).splitlines():
            heading = _MARKDOWN_HEADING.match(line)
            if heading:
                flush()
                headings.enter(len(heading[1]), heading[2])
            elif line.strip():
                paragraph.append(line.strip())
            else:
                flush()
        flush()
        return blocks


class PlainTextParser:
    """Текст без разметки: только абзацы, путь заголовков пустой."""

    def parse(self, content: bytes) -> list[Block]:
        paragraphs = re.split(r"\n\s*\n", _decode(content))
        return [Block(p.strip(), ()) for p in paragraphs if p.strip()]


class DocxParser:
    """Структуру задают стили Title и Heading N. Таблицы и колонтитулы не извлекаются."""

    def __init__(self, max_uncompressed_bytes: int = MAX_DOCX_UNCOMPRESSED_BYTES) -> None:
        self._max_uncompressed_bytes = max_uncompressed_bytes

    def parse(self, content: bytes) -> list[Block]:
        self._ensure_safe_archive(content)
        try:
            document = docx.Document(io.BytesIO(content))
        except Exception as e:  # недоверенный файл: любая ошибка разбора — «битый документ»
            raise InvalidDocumentError from e
        headings = _HeadingPath()
        blocks: list[Block] = []
        for paragraph in document.paragraphs:
            text = paragraph.text.strip()
            if not text:
                continue
            level = _docx_heading_level(paragraph.style.name if paragraph.style else None)
            if level is None:
                blocks.append(Block(text, headings.current))
            else:
                headings.enter(level, text)
        return blocks

    def _ensure_safe_archive(self, content: bytes) -> None:
        # DOCX — zip: файл в килобайты может распаковаться в гигабайты (zip-бомба). zipfile
        # не отдаёт больше заявленного file_size, поэтому проверки заявленных размеров достаточно.
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                unpacked = sum(info.file_size for info in archive.infolist())
        except zipfile.BadZipFile as e:
            raise InvalidDocumentError from e
        if unpacked > self._max_uncompressed_bytes:
            raise InvalidDocumentError


def _docx_heading_level(style_name: str | None) -> int | None:
    if style_name == "Title":
        return 0
    match = _DOCX_HEADING_STYLE.match(style_name or "")
    return int(match[1]) if match else None


@dataclass(frozen=True, slots=True)
class _PdfLine:
    page: int
    block: int
    size: float
    text: str


class PdfParser:
    """Заголовки определяются по размеру шрифта: чем крупнее, тем выше уровень.

    Эвристика для документов без закладок. Сканы без текстового слоя дают пустой результат:
    OCR не поддерживается.
    """

    def parse(self, content: bytes) -> list[Block]:
        lines = list(self._lines(content))
        if not lines:
            return []
        weights: Counter[float] = Counter()
        for line in lines:
            weights[line.size] += len(line.text)
        body_size = weights.most_common(1)[0][0]
        heading_sizes = sorted(
            {line.size for line in lines if line.size > body_size * _PDF_HEADING_SCALE},
            reverse=True,
        )
        level_of = {size: level for level, size in enumerate(heading_sizes, 1)}

        headings = _HeadingPath()
        blocks: list[Block] = []
        paragraph: list[_PdfLine] = []

        def flush() -> None:
            if paragraph:
                text = "\n".join(line.text for line in paragraph)
                blocks.append(Block(text, headings.current, page=paragraph[0].page))
                paragraph.clear()

        for line in lines:
            if line.size in level_of:
                flush()
                headings.enter(level_of[line.size], line.text)
            else:
                if paragraph and (line.page, line.block) != (paragraph[0].page, paragraph[0].block):
                    flush()
                paragraph.append(line)
        flush()
        return blocks

    @staticmethod
    def _lines(content: bytes) -> Iterator[_PdfLine]:
        try:
            pdf = pymupdf.open(stream=content, filetype="pdf")
        except pymupdf.FileDataError as e:
            raise InvalidDocumentError from e
        with pdf:
            if pdf.needs_pass:
                raise InvalidDocumentError
            for page in pdf.pages():
                for block in page.get_text("dict")["blocks"]:
                    for line in block.get("lines", []):
                        spans = line["spans"]
                        text = "".join(span["text"] for span in spans).strip()
                        if text:
                            size = round(max(span["size"] for span in spans), 1)
                            yield _PdfLine(page.number + 1, block["number"], size, text)
