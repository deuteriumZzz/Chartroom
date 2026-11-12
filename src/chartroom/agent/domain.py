"""Агент с вызовом функций (M4, FR-16…FR-22): инструменты, шаги, итоговый ответ.

Описание инструмента — JSON Schema аргументов. Ту же схему получает модель (function
declarations) и по ней же проверяются аргументы её вызовов (FR-18): одно описание вместо двух.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from chartroom.shared.errors import InvalidInputError
from chartroom.shared.language import Language
from chartroom.shared.quotes import quote_in, words
from chartroom.shared.schema import Schema

MAX_STEPS = 4  # FR-20: больше шагов — честный отказ, а не бесконечный цикл
# FR-20: лимит на весь запрос. Шаг ограничен таймаутом модели (shared.gemini.PER_MODEL_HTTP), но
# 4 шага по цепочке моделей без общего лимита растянулись бы на минуты.
MAX_REQUEST_SECONDS = 60
MAX_QUESTION_LENGTH = 1000
MAX_SEARCH_QUERY = 500
DEFAULT_SEARCH_TOP_K = 5
SUBMIT_ANSWER = "submit_answer"

NO_DATA_TEXT = {
    Language.RU: "Не удалось получить данные для ответа.",
    Language.EN: "Could not get the data needed to answer.",
}
REFUSAL_TEXT = {
    Language.RU: "В доступных данных ответа нет.",
    Language.EN: "The available data does not contain an answer.",
}


class InvalidAgentQuestionError(InvalidInputError):
    message = f"Question must be between 1 and {MAX_QUESTION_LENGTH} characters"


class InvalidSubmissionError(InvalidInputError):
    message = "submit_answer needs a string 'answer' and a boolean 'refusal'"


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    parameters: Schema


DATA_TOOLS = (
    ToolSpec(
        "search_procedures",
        "Search the fleet's safety procedures (SMS). Returns numbered passages; quote them in "
        "submit_answer by their number.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to look for"},
                "top_k": {"type": "integer", "minimum": 1, "maximum": 10},
            },
            "required": ["query"],
        },
    ),
    ToolSpec(
        "list_reports",
        "List the user's reports and checklists, newest first (a captain sees everyone's).",
        {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["draft", "needs_review", "accepted"]},
                "template": {
                    "type": "string",
                    "description": "Template name, e.g. drill_checklist",
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
        },
    ),
    ToolSpec(
        "get_report",
        "One report with its extracted data and validation issues.",
        {
            "type": "object",
            "properties": {"report_id": {"type": "integer", "minimum": 1}},
            "required": ["report_id"],
        },
    ),
    ToolSpec(
        "get_report_template",
        "Fields of a report template and which of them are required.",
        {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
    ),
    ToolSpec(
        "get_active_document_version",
        "Which revision of a procedure is currently in force.",
        {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]},
    ),
)
SUBMIT_TOOL = ToolSpec(
    SUBMIT_ANSWER,
    "Finish with the final answer. Cite procedure passages by number with a verbatim quote.",
    {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "refusal": {"type": "boolean"},
            "citations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"passage": {"type": "integer"}, "quote": {"type": "string"}},
                    "required": ["passage", "quote"],
                },
            },
        },
        "required": ["answer", "refusal"],
    },
)
TOOLS = (*DATA_TOOLS, SUBMIT_TOOL)
DATA_TOOL_SPECS = {tool.name: tool for tool in DATA_TOOLS}


@dataclass(frozen=True, slots=True)
class ToolCall:
    name: str
    args: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolResult:
    name: str
    content: dict[str, Any]
    ok: bool


@dataclass(frozen=True, slots=True)
class ModelTurn:
    """Ход модели: вызовы инструментов или (если их нет) просто текст."""

    calls: tuple[ToolCall, ...]
    text: str | None


@dataclass(frozen=True, slots=True)
class Source:
    """Фрагмент процедуры, который вернул search_procedures; номер — сквозной в рамках запроса."""

    number: int
    document_id: int
    version_id: int
    title: str
    section_path: str
    page: int | None
    text: str


@dataclass(frozen=True, slots=True)
class Citation:
    document_id: int
    version_id: int
    title: str
    section_path: str
    page: int | None
    quote: str


@dataclass(frozen=True, slots=True)
class ToolCallRecord:
    step: int
    name: str
    args: dict[str, Any]
    ok: bool
    error: str | None
    latency_ms: int


@dataclass(frozen=True, slots=True)
class AgentAnswer:
    text: str
    language: Language
    refusal: bool
    citations: tuple[Citation, ...]
    citation_warning: bool
    steps: int


@dataclass(frozen=True, slots=True)
class AgentViewer:
    """От чьего имени выполняются инструменты. Модель этого не задаёт (FR-19)."""

    user_id: int
    is_supervisor: bool


@dataclass(frozen=True, slots=True)
class AgentRun:
    user_id: int
    question: str
    answer: AgentAnswer
    tool_calls: tuple[ToolCallRecord, ...]
    latency_ms: int
    model: str | None
    prompt_version: str


@dataclass(frozen=True, slots=True)
class AgentReply:
    run_id: int
    answer: AgentAnswer
    tool_calls: tuple[ToolCallRecord, ...]


def normalize_question(raw: str) -> str:
    question = " ".join(raw.split())
    if not question or len(question) > MAX_QUESTION_LENGTH:
        raise InvalidAgentQuestionError
    return question


def finalize(
    args: dict[str, Any], sources: Sequence[Source], language: Language, steps: int
) -> AgentAnswer:
    """Итог из submit_answer: цитаты проверяются по фрагментам этого запроса (FR-22)."""
    text, refusal = args.get("answer"), args.get("refusal")
    if not isinstance(text, str) or not isinstance(refusal, bool):
        raise InvalidSubmissionError
    if refusal or not text.strip():
        return AgentAnswer(REFUSAL_TEXT[language], language, True, (), False, steps)
    by_number = {source.number: source for source in sources}
    citations: list[Citation] = []
    seen: set[tuple[int, tuple[str, ...]]] = set()
    warning = False
    for item in args.get("citations") or []:
        number = item.get("passage") if isinstance(item, dict) else None
        quote = item.get("quote") if isinstance(item, dict) else None
        source = by_number.get(number) if isinstance(number, int) else None
        if source is None or not isinstance(quote, str) or not quote_in(source.text, quote):
            warning = True  # ссылка не на фрагмент этого запроса или цитата не из него
            continue
        key = (source.number, words(quote))
        if key not in seen:
            seen.add(key)
            citations.append(
                Citation(
                    source.document_id,
                    source.version_id,
                    source.title,
                    source.section_path,
                    source.page,
                    quote.strip(),
                )
            )
    return AgentAnswer(text.strip(), language, False, tuple(citations), warning, steps)
