"""Вопросы, ответы и цитаты. Чистые правила — без фреймворков и I/O."""

import html
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from chartroom.shared.errors import InvalidInputError, NotFoundError
from chartroom.shared.language import Language
from chartroom.shared.quotes import quote_in, words

MAX_QUESTION_LENGTH = 1000
DEFAULT_TOP_K = 5
MAX_TOP_K = 20
MAX_FEEDBACK_COMMENT = 1000
MAX_HISTORY_PAGE = 100


REFUSAL_TEXT = {
    Language.RU: "В загруженных документах ответа нет.",
    Language.EN: "The uploaded documents do not contain an answer.",
}


class InvalidQuestionError(InvalidInputError):
    message = f"Question must be between 1 and {MAX_QUESTION_LENGTH} characters"


class InvalidFeedbackError(InvalidInputError):
    message = f"Feedback comment must be at most {MAX_FEEDBACK_COMMENT} characters"


class QueryNotFoundError(NotFoundError):
    # И для чужого запроса тоже: по ответу нельзя узнать, что такой запрос существует (IDOR).
    message = "Query not found"


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
class RawCitation:
    """Ссылка, как её вернула модель: номер фрагмента в контексте и дословная цитата."""

    passage: int
    quote: str


@dataclass(frozen=True, slots=True)
class GeneratedAnswer:
    """Ответ модели как есть: текст, непроверенные ссылки, отказ и какая модель ответила."""

    text: str
    citations: tuple[RawCitation, ...]
    refusal: bool
    model: str


@dataclass(frozen=True, slots=True)
class Answer:
    text: str
    language: Language
    refusal: bool
    citations: tuple[Citation, ...]
    citation_warning: bool = False  # модель сослалась на то, чего нет в контексте (FR-6)

    @classmethod
    def refused(cls, language: Language, citation_warning: bool = False) -> "Answer":
        return cls(REFUSAL_TEXT[language], language, True, (), citation_warning)


@dataclass(frozen=True, slots=True)
class Reply:
    """Ответ вместе с номером записи в журнале — по нему пользователь оставляет отзыв."""

    query_id: int
    answer: Answer


@dataclass(frozen=True, slots=True)
class Viewer:
    """Кто смотрит журнал. Роль переводит в это понятие HTTP-слой: qa не знает о ролях."""

    user_id: int
    sees_all_queries: bool


@dataclass(frozen=True, slots=True)
class QueryEntry:
    """Новая запись журнала запросов."""

    user_id: int
    question: str
    answer: Answer
    latency_ms: int
    model: str | None  # None — ответ (отказ) без вызова модели
    prompt_version: str | None


@dataclass(frozen=True, slots=True)
class Feedback:
    useful: bool
    comment: str | None


@dataclass(frozen=True, slots=True)
class LoggedQuery:
    id: int
    user_id: int
    question: str
    answer: Answer
    latency_ms: int
    model: str | None
    prompt_version: str | None
    created_at: datetime
    feedback: Feedback | None


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


def render_context(question: str, language: Language, passages: Sequence[Passage]) -> str:
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


def verify_citations(
    raw: Sequence[RawCitation], passages: Sequence[Passage]
) -> tuple[tuple[Citation, ...], bool]:
    """FR-6: ссылка остаётся, только если указывает на переданный фрагмент и её цитата
    дословно (по словам) в нём есть. Иначе ссылка удаляется, а ответ получает предупреждение.

    Сравнение по последовательности слов: пунктуация, регистр и markdown не мешают,
    а искажённая или чужая цитата не проходит.
    """
    citations: list[Citation] = []
    seen: set[tuple[int, tuple[str, ...]]] = set()
    warning = False
    for item in raw:
        passage = passages[item.passage - 1] if 1 <= item.passage <= len(passages) else None
        if passage is None or not quote_in(passage.text, item.quote):
            warning = True
            continue
        key = (item.passage, words(item.quote))
        if key in seen:
            continue
        seen.add(key)
        citations.append(
            Citation(
                passage.document_id,
                passage.version_id,
                passage.title,
                passage.section_path,
                passage.page,
                item.quote.strip(),
            )
        )
    return tuple(citations), warning


def normalize_comment(raw: str | None) -> str | None:
    comment = (raw or "").strip()
    if len(comment) > MAX_FEEDBACK_COMMENT:
        raise InvalidFeedbackError
    return comment or None
