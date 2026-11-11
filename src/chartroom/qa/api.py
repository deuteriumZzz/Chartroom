"""HTTP-адаптер модуля qa."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from chartroom.identity.api import OfficerUser
from chartroom.qa.domain import DEFAULT_TOP_K, MAX_QUESTION_LENGTH, MAX_TOP_K
from chartroom.qa.service import QuestionService

router = APIRouter(tags=["qa"])


def get_questions(request: Request) -> QuestionService:
    questions: QuestionService = request.app.state.container.questions
    return questions


QuestionsDep = Annotated[QuestionService, Depends(get_questions)]


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_LENGTH)
    top_k: int = Field(default=DEFAULT_TOP_K, ge=1, le=MAX_TOP_K)


class PassageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: int
    version_id: int
    title: str
    section_path: str
    page: int | None
    text: str
    score: float


class AskResponse(BaseModel):
    passages: list[PassageResponse]


@router.post("/ask")
async def ask(request: AskRequest, _: OfficerUser, questions: QuestionsDep) -> AskResponse:
    """Фрагменты актуальных процедур, подтверждающие ответ на вопрос (RU или EN)."""
    passages = await questions.ask(request.question, request.top_k)
    return AskResponse(passages=[PassageResponse.model_validate(p) for p in passages])
