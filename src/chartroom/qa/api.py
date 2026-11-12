"""HTTP-адаптер модуля qa."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from chartroom.identity.api import OfficerUser, limit_per_user
from chartroom.identity.domain import Role, User
from chartroom.qa.domain import (
    DEFAULT_TOP_K,
    MAX_FEEDBACK_COMMENT,
    MAX_HISTORY_PAGE,
    MAX_QUESTION_LENGTH,
    MAX_TOP_K,
    Answer,
    LoggedQuery,
    Viewer,
)
from chartroom.qa.service import QuestionService
from chartroom.shared.language import Language

router = APIRouter(tags=["qa"])


def get_questions(request: Request) -> QuestionService:
    questions: QuestionService = request.app.state.container.questions
    return questions


QuestionsDep = Annotated[QuestionService, Depends(get_questions)]


def _viewer(user: User) -> Viewer:
    # Роль переводится в понятие qa здесь, на краю модуля: ядро qa о ролях не знает.
    return Viewer(user.id, sees_all_queries=user.role.is_at_least(Role.CAPTAIN))


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_LENGTH)
    top_k: int = Field(default=DEFAULT_TOP_K, ge=1, le=MAX_TOP_K)


class CitationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: int
    version_id: int
    title: str
    section_path: str
    page: int | None
    quote: str


class AnswerFields(BaseModel):
    answer: str
    language: Language
    refusal: bool
    citation_warning: bool  # модель сослалась на то, чего не было в контексте; такие ссылки удалены
    citations: list[CitationResponse]

    @staticmethod
    def of(answer: Answer) -> dict[str, object]:
        return {
            "answer": answer.text,
            "language": answer.language,
            "refusal": answer.refusal,
            "citation_warning": answer.citation_warning,
            "citations": [CitationResponse.model_validate(c) for c in answer.citations],
        }


class AskResponse(AnswerFields):
    query_id: int


class FeedbackRequest(BaseModel):
    useful: bool
    comment: str | None = Field(default=None, max_length=MAX_FEEDBACK_COMMENT)


class FeedbackResponse(BaseModel):
    useful: bool
    comment: str | None


class QueryResponse(AnswerFields):
    id: int
    user_id: int
    question: str
    latency_ms: int
    model: str | None
    prompt_version: str | None
    created_at: datetime
    feedback: FeedbackResponse | None

    @classmethod
    def from_domain(cls, query: LoggedQuery) -> "QueryResponse":
        feedback = query.feedback
        return cls(
            id=query.id,
            user_id=query.user_id,
            question=query.question,
            latency_ms=query.latency_ms,
            model=query.model,
            prompt_version=query.prompt_version,
            created_at=query.created_at,
            feedback=FeedbackResponse(useful=feedback.useful, comment=feedback.comment)
            if feedback
            else None,
            **AnswerFields.of(query.answer),
        )


@router.post("/ask", dependencies=[Depends(limit_per_user("ask"))])
async def ask(request: AskRequest, user: OfficerUser, questions: QuestionsDep) -> AskResponse:
    """Ответ по актуальным процедурам с проверенными цитатами — или отказ, если ответа нет.

    Язык ответа — язык вопроса (RU или EN). `query_id` нужен для отзыва.
    """
    reply = await questions.ask(request.question, user.id, request.top_k)
    return AskResponse(query_id=reply.query_id, **AnswerFields.of(reply.answer))


@router.post("/ask/{query_id}/feedback", status_code=status.HTTP_204_NO_CONTENT)
async def give_feedback(
    query_id: int, request: FeedbackRequest, user: OfficerUser, questions: QuestionsDep
) -> None:
    """Отзыв на свой ответ (FR-7). Повторный отзыв заменяет прежний."""
    await questions.give_feedback(query_id, _viewer(user), request.useful, request.comment)


@router.get("/queries")
async def list_queries(
    user: OfficerUser,
    questions: QuestionsDep,
    limit: Annotated[int, Query(ge=1, le=MAX_HISTORY_PAGE)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[QueryResponse]:
    """Журнал запросов, новые сначала: officer видит свои, captain и admin — все."""
    queries = await questions.history(_viewer(user), limit, offset)
    return [QueryResponse.from_domain(q) for q in queries]
