from datetime import UTC, datetime
from typing import Any, Self

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship

from chartroom.agent.domain import AgentRun
from chartroom.shared.database import Base, SqlAlchemyUnitOfWork
from chartroom.shared.language import Language


def _now() -> datetime:
    return datetime.now(UTC)


class ToolCallRecord(Base):
    """Аудит каждого вызова инструмента."""

    __tablename__ = "tool_calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True)
    step: Mapped[int]
    name: Mapped[str] = mapped_column(String(64))
    args: Mapped[dict[str, Any]] = mapped_column(JSONB)
    ok: Mapped[bool]
    error: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int]


class AgentRunRecord(Base):
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    question: Mapped[str] = mapped_column(Text)
    language: Mapped[Language] = mapped_column(
        Enum(
            Language,
            name="agent_language",
            native_enum=False,
            create_constraint=True,
            length=2,
            values_callable=lambda members: [m.value for m in members],
        )
    )
    answer: Mapped[str] = mapped_column(Text)
    refusal: Mapped[bool]
    citation_warning: Mapped[bool]
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    steps: Mapped[int]
    latency_ms: Mapped[int]
    model: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    tool_calls: Mapped[list[ToolCallRecord]] = relationship(order_by=ToolCallRecord.id)


class SqlAgentRunLog:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, run: AgentRun) -> int:
        answer = run.answer
        record = AgentRunRecord(
            user_id=run.user_id,
            question=run.question,
            language=answer.language,
            answer=answer.text,
            refusal=answer.refusal,
            citation_warning=answer.citation_warning,
            citations=[
                {
                    "document_id": c.document_id,
                    "version_id": c.version_id,
                    "title": c.title,
                    "section_path": c.section_path,
                    "page": c.page,
                    "quote": c.quote,
                }
                for c in answer.citations
            ],
            steps=answer.steps,
            latency_ms=run.latency_ms,
            model=run.model,
            prompt_version=run.prompt_version,
            tool_calls=[
                ToolCallRecord(
                    step=c.step,
                    name=c.name,
                    args=c.args,
                    ok=c.ok,
                    error=c.error,
                    latency_ms=c.latency_ms,
                )
                for c in run.tool_calls
            ],
        )
        self._session.add(record)
        await self._session.flush()
        return record.id


class SqlAgentUnitOfWork(SqlAlchemyUnitOfWork):
    runs: SqlAgentRunLog

    async def __aenter__(self) -> Self:
        await super().__aenter__()
        self.runs = SqlAgentRunLog(self.session)
        return self
