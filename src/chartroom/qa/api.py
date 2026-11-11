"""HTTP-адаптер модуля qa."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from chartroom.identity.api import OfficerUser
from chartroom.qa.domain import DEFAULT_TOP_K, MAX_QUESTION_LENGTH, MAX_TOP_K, AnswerLanguage
from chartroom.qa.service import QuestionService

router = APIRouter(tags=["qa"])


def get_questions(request: Request) -> QuestionService:
    questions: QuestionService = request.app.state.container.questions
    return questions


QuestionsDep = Annotated[QuestionService, Depends(get_questions)]


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


class AskResponse(BaseModel):
    answer: str
    language: AnswerLanguage
    refusal: bool
    citation_warning: bool  # модель сослалась на то, чего не было в контексте; такие ссылки удалены
    citations: list[CitationResponse]


@router.post("/ask")
async def ask(request: AskRequest, _: OfficerUser, questions: QuestionsDep) -> AskResponse:
    """Ответ по актуальным процедурам с цитатами — или отказ, если в документах ответа нет.

    Язык ответа — язык вопроса (RU или EN).
    """
    answer = await questions.ask(request.question, request.top_k)
    return AskResponse(
        answer=answer.text,
        language=answer.language,
        refusal=answer.refusal,
        citation_warning=answer.citation_warning,
        citations=[CitationResponse.model_validate(c) for c in answer.citations],
    )
