"""Вопросы, ответы и цитаты. Чистые правила — без фреймворков и I/O."""

import html
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from chartroom.shared.errors import InvalidInputError

MAX_QUESTION_LENGTH = 1000
DEFAULT_TOP_K = 5
MAX_TOP_K = 20
# Доля кириллицы, начиная с которой вопрос считается русским: «Что такое ECDIS MOB?» — русский.
_RUSSIAN_SHARE = 0.3


class AnswerLanguage(StrEnum):
    RU = "ru"
    EN = "en"


REFUSAL_TEXT = {
    AnswerLanguage.RU: "В загруженных документах ответа нет.",
    AnswerLanguage.EN: "The uploaded documents do not contain an answer.",
}


class InvalidQuestionError(InvalidInputError):
    message = f"Question must be between 1 and {MAX_QUESTION_LENGTH} characters"


@dataclass(frozen=True, slots=True)
class Passage:
    """Фрагмент процедуры, найденный по вопросу, с данными для цитаты."""

    document_id: int
    version_id: int
    title: str
    section_path: str
    page: int | None
    text: str
    score: float  # порядок в выдаче (RRF)
    similarity: float  # близость к вопросу (cosine), по ней решается отказ


@dataclass(frozen=True, slots=True)
class Citation:
    document_id: int
    version_id: int
    title: str
    section_path: str
    page: int | None
    quote: str


@dataclass(frozen=True, slots=True)
class GeneratedAnswer:
    """Ответ модели как есть: текст, номера фрагментов-источников, признак отказа."""

    text: str
    citations: tuple[int, ...]
    refusal: bool


@dataclass(frozen=True, slots=True)
class Answer:
    text: str
    language: AnswerLanguage
    refusal: bool
    citations: tuple[Citation, ...]

    @classmethod
    def refused(cls, language: AnswerLanguage) -> "Answer":
        return cls(REFUSAL_TEXT[language], language, refusal=True, citations=())


@dataclass(frozen=True, slots=True)
class RefusalPolicy:
    """Отказ без вызова модели, если ответ нечем подтвердить.

    Решает сходство с вопросом, а не оценка RRF: та показывает только порядок (ADR-006).
    """

    min_similarity: float

    def allows(self, passages: Sequence[Passage]) -> bool:
        return bool(passages) and max(p.similarity for p in passages) >= self.min_similarity


def normalize_question(raw: str) -> str:
    question = " ".join(raw.split())
    if not question or len(question) > MAX_QUESTION_LENGTH:
        raise InvalidQuestionError
    return question


def detect_language(text: str) -> AnswerLanguage:
    letters = [c for c in text if c.isalpha()]
    cyrillic = sum("Ѐ" <= c <= "ӿ" for c in letters)
    return (
        AnswerLanguage.RU
        if letters and cyrillic / len(letters) >= _RUSSIAN_SHARE
        else AnswerLanguage.EN
    )


def render_context(question: str, language: AnswerLanguage, passages: Sequence[Passage]) -> str:
    """Вопрос и фрагменты для модели.

    Всё внутри тегов — недоверенные данные. Экранирование не даёт тексту документа закрыть
    тег и выдать продолжение за инструкцию (prompt injection через «</passage>»).
    """
    lines = [f'<question language="{language}">{html.escape(question)}</question>', "<passages>"]
    for number, passage in enumerate(passages, 1):
        lines.append(
            f'<passage id="{number}" document="{html.escape(passage.title)}" '
            f'section="{html.escape(passage.section_path)}">\n{html.escape(passage.text)}\n</passage>'
        )
    lines.append("</passages>")
    return "\n".join(lines)


def cited(generated: GeneratedAnswer, passages: Sequence[Passage]) -> tuple[Citation, ...]:
    """Номера фрагментов из ответа модели → цитаты. Номер вне контекста отбрасывается."""
    numbers = dict.fromkeys(n for n in generated.citations if 1 <= n <= len(passages))
    return tuple(
        Citation(p.document_id, p.version_id, p.title, p.section_path, p.page, p.text)
        for p in (passages[n - 1] for n in numbers)
    )
