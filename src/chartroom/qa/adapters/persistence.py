from datetime import UTC, datetime
from typing import Self

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    select,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship, selectinload

from chartroom.qa.domain import (
    Answer,
    AnswerLanguage,
    Citation,
    Feedback,
    LoggedQuery,
    QueryEntry,
)
from chartroom.shared.database import Base, SqlAlchemyUnitOfWork


def _now() -> datetime:
    return datetime.now(UTC)


class CitationRecord(Base):
    __tablename__ = "citations"
    __table_args__ = (UniqueConstraint("query_id", "position", name="uq_citations_query_position"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    query_id: Mapped[int] = mapped_column(ForeignKey("queries.id", ondelete="CASCADE"))
    position: Mapped[int]
    # Без внешнего ключа на версии документов: журнал аудита переживает удаление документа.
    document_id: Mapped[int]
    version_id: Mapped[int]
    title: Mapped[str] = mapped_column(String(300))
    section_path: Mapped[str] = mapped_column(Text)
    page: Mapped[int | None]
    quote: Mapped[str] = mapped_column(Text)


class FeedbackRecord(Base):
    __tablename__ = "feedback"

    query_id: Mapped[int] = mapped_column(
        ForeignKey("queries.id", ondelete="CASCADE"), primary_key=True
    )
    useful: Mapped[bool]
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class QueryRecord(Base):
    __tablename__ = "queries"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    question: Mapped[str] = mapped_column(Text)
    language: Mapped[AnswerLanguage] = mapped_column(
        Enum(
            AnswerLanguage,
            name="answer_language",
            native_enum=False,
            create_constraint=True,
            length=2,
            values_callable=lambda members: [m.value for m in members],
        )
    )
    answer: Mapped[str] = mapped_column(Text)
    refusal: Mapped[bool]
    citation_warning: Mapped[bool]
    latency_ms: Mapped[int]
    model: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    citations: Mapped[list[CitationRecord]] = relationship(order_by=CitationRecord.position)
    feedback: Mapped[FeedbackRecord | None] = relationship()

    def to_domain(self) -> LoggedQuery:
        citations = tuple(
            Citation(c.document_id, c.version_id, c.title, c.section_path, c.page, c.quote)
            for c in self.citations
        )
        answer = Answer(self.answer, self.language, self.refusal, citations, self.citation_warning)
        feedback = Feedback(self.feedback.useful, self.feedback.comment) if self.feedback else None
        return LoggedQuery(
            id=self.id,
            user_id=self.user_id,
            question=self.question,
            answer=answer,
            latency_ms=self.latency_ms,
            model=self.model,
            prompt_version=self.prompt_version,
            created_at=self.created_at,
            feedback=feedback,
        )


_WITH_DETAILS = (selectinload(QueryRecord.citations), selectinload(QueryRecord.feedback))


class SqlQueryLog:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, entry: QueryEntry) -> int:
        answer = entry.answer
        record = QueryRecord(
            user_id=entry.user_id,
            question=entry.question,
            language=answer.language,
            answer=answer.text,
            refusal=answer.refusal,
            citation_warning=answer.citation_warning,
            latency_ms=entry.latency_ms,
            model=entry.model,
            prompt_version=entry.prompt_version,
            citations=[
                CitationRecord(
                    position=position,
                    document_id=c.document_id,
                    version_id=c.version_id,
                    title=c.title,
                    section_path=c.section_path,
                    page=c.page,
                    quote=c.quote,
                )
                for position, c in enumerate(answer.citations)
            ],
        )
        self._session.add(record)
        await self._session.flush()
        return record.id

    async def get(self, query_id: int) -> LoggedQuery | None:
        record = await self._session.scalar(
            select(QueryRecord).where(QueryRecord.id == query_id).options(*_WITH_DETAILS)
        )
        return record.to_domain() if record else None

    async def list(self, user_id: int | None, limit: int, offset: int) -> list[LoggedQuery]:
        statement = select(QueryRecord).options(*_WITH_DETAILS)
        if user_id is not None:
            statement = statement.where(QueryRecord.user_id == user_id)
        records = await self._session.scalars(
            statement.order_by(QueryRecord.id.desc()).limit(limit).offset(offset)
        )
        return [record.to_domain() for record in records]


class SqlFeedbackRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, query_id: int, feedback: Feedback) -> None:
        # Один отзыв на ответ: повторный заменяет прежний (upsert, без гонки «прочитал — записал»).
        values = {"useful": feedback.useful, "comment": feedback.comment, "created_at": _now()}
        await self._session.execute(
            insert(FeedbackRecord)
            .values(query_id=query_id, **values)
            .on_conflict_do_update(index_elements=[FeedbackRecord.query_id], set_=values)
        )


class SqlQaUnitOfWork(SqlAlchemyUnitOfWork):
    queries: SqlQueryLog
    feedback: SqlFeedbackRepository

    async def __aenter__(self) -> Self:
        await super().__aenter__()
        self.queries = SqlQueryLog(self.session)
        self.feedback = SqlFeedbackRepository(self.session)
        return self
