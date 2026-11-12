"""HTTP-адаптер агента: POST /agent/ask (FR-16)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from chartroom.agent.domain import MAX_QUESTION_LENGTH, AgentViewer
from chartroom.agent.service import AgentService
from chartroom.identity.api import OfficerUser
from chartroom.identity.domain import Role
from chartroom.shared.language import Language

router = APIRouter(prefix="/agent", tags=["agent"])


def get_agent(request: Request) -> AgentService:
    agent: AgentService = request.app.state.container.agent
    return agent


AgentDep = Annotated[AgentService, Depends(get_agent)]


class AgentRequest(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_LENGTH)


class CitationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: int
    version_id: int
    title: str
    section_path: str
    page: int | None
    quote: str


class ToolCallResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    step: int
    name: str
    args: dict[str, Any]
    ok: bool
    error: str | None


class AgentResponse(BaseModel):
    run_id: int
    answer: str
    language: Language
    refusal: bool
    citation_warning: bool
    citations: list[CitationResponse]
    tool_calls: list[ToolCallResponse]  # видно, какие данные агент запросил и что получил


@router.post("/ask")
async def ask_agent(request: AgentRequest, user: OfficerUser, agent: AgentDep) -> AgentResponse:
    """Вопрос агенту: модель сама запрашивает процедуры, отчёты и шаблоны через функции.

    Функции выполняются от имени текущего пользователя и только читают данные.
    """
    viewer = AgentViewer(user.id, is_supervisor=user.role.is_at_least(Role.CAPTAIN))
    reply = await agent.ask(request.question, viewer)
    answer = reply.answer
    return AgentResponse(
        run_id=reply.run_id,
        answer=answer.text,
        language=answer.language,
        refusal=answer.refusal,
        citation_warning=answer.citation_warning,
        citations=[CitationResponse.model_validate(c) for c in answer.citations],
        tool_calls=[ToolCallResponse.model_validate(c) for c in reply.tool_calls],
    )
