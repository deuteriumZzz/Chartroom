"""Вопросы по процедурам и найденные фрагменты. Чистые правила — без фреймворков и I/O."""

from dataclasses import dataclass

from chartroom.shared.errors import InvalidInputError

MAX_QUESTION_LENGTH = 1000
DEFAULT_TOP_K = 5
MAX_TOP_K = 20


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


def normalize_question(raw: str) -> str:
    question = " ".join(raw.split())
    if not question or len(question) > MAX_QUESTION_LENGTH:
        raise InvalidQuestionError
    return question
