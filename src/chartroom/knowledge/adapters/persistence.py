import hashlib
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Self

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    delete,
    select,
    text,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from chartroom.knowledge.domain.indexing import IndexedChunk
from chartroom.knowledge.domain.models import (
    Document,
    DocumentAlreadyExistsError,
    DocumentUpload,
    DocumentVersion,
    DuplicateFileError,
    DuplicateVersionError,
    IndexingStatus,
    Language,
)
from chartroom.shared.database import Base, SqlAlchemyUnitOfWork


def _enum(enum_class: type[StrEnum], name: str) -> Enum:
    return Enum(
        enum_class,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=16,
        values_callable=lambda members: [m.value for m in members],
    )


class DocumentRecord(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("title_key", "language", name="uq_documents_title_language"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    # Ключ без учёта регистра: «Fire safety» и «FIRE SAFETY» — один документ.
    title_key: Mapped[str] = mapped_column(String(300))
    language: Mapped[Language] = mapped_column(_enum(Language, "document_language"))

    def to_domain(self) -> Document:
        return Document(id=self.id, title=self.title, language=self.language)


class DocumentVersionRecord(Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "label", name="uq_document_versions_label"),
        UniqueConstraint("document_id", "checksum", name="uq_document_versions_checksum"),
        # Не больше одной активной версии на документ — инвариант держит сама БД.
        Index(
            "uq_document_versions_active",
            "document_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(String(50))
    issued_on: Mapped[date] = mapped_column(Date)
    filename: Mapped[str] = mapped_column(String(255))
    checksum: Mapped[str] = mapped_column(String(64))
    # Файл не загружается при чтении версий: он нужен только worker-у.
    content: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    status: Mapped[IndexingStatus] = mapped_column(_enum(IndexingStatus, "indexing_status"))
    error: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(default=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    def to_domain(self) -> DocumentVersion:
        return DocumentVersion(
            id=self.id,
            document_id=self.document_id,
            label=self.label,
            issued_on=self.issued_on,
            filename=self.filename,
            checksum=self.checksum,
            status=self.status,
            is_active=self.is_active,
            uploaded_at=self.uploaded_at,
            error=self.error,
        )


class ChunkRecord(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("version_id", "chunk_index", name="uq_chunks_version_index"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("document_versions.id", ondelete="CASCADE"))
    chunk_index: Mapped[int]
    section_path: Mapped[str] = mapped_column(Text)
    page: Mapped[int | None]
    text_hash: Mapped[str] = mapped_column(String(64))
    qdrant_id: Mapped[uuid.UUID]


class SqlDocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, document_id: int) -> Document | None:
        record = await self._session.get(DocumentRecord, document_id)
        return record.to_domain() if record else None

    async def find(self, title: str, language: Language) -> Document | None:
        record = await self._session.scalar(
            select(DocumentRecord).where(
                DocumentRecord.title_key == title.casefold(), DocumentRecord.language == language
            )
        )
        return record.to_domain() if record else None

    async def add(self, title: str, language: Language) -> Document:
        record = DocumentRecord(title=title, title_key=title.casefold(), language=language)
        self._session.add(record)
        try:
            await self._session.flush()
        except IntegrityError as e:
            raise DocumentAlreadyExistsError from e
        return record.to_domain()


class SqlVersionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, version_id: int) -> DocumentVersion | None:
        record = await self._session.get(DocumentVersionRecord, version_id)
        return record.to_domain() if record else None

    async def list_for(self, document_id: int) -> list[DocumentVersion]:
        records = await self._session.scalars(
            select(DocumentVersionRecord)
            .where(DocumentVersionRecord.document_id == document_id)
            .order_by(DocumentVersionRecord.id)
        )
        return [record.to_domain() for record in records]

    async def add(self, document_id: int, upload: DocumentUpload, checksum: str) -> DocumentVersion:
        record = DocumentVersionRecord(
            document_id=document_id,
            label=upload.label,
            issued_on=upload.issued_on,
            filename=upload.filename,
            checksum=checksum,
            content=upload.content,
            status=IndexingStatus.PENDING,
            is_active=False,
        )
        self._session.add(record)
        try:
            await self._session.flush()
        except IntegrityError as e:
            # Гонка двух загрузок: проверка в сервисе прошла, но БД уже содержит такую версию.
            duplicate_file = "uq_document_versions_checksum" in str(e.orig)
            raise (DuplicateFileError if duplicate_file else DuplicateVersionError) from e
        return record.to_domain()

    async def get_content(self, version_id: int) -> bytes:
        result = await self._session.execute(
            select(DocumentVersionRecord.content).where(DocumentVersionRecord.id == version_id)
        )
        return result.scalar_one()

    async def set_status(
        self, version_id: int, status: IndexingStatus, error: str | None = None
    ) -> None:
        await self._session.execute(
            update(DocumentVersionRecord)
            .where(DocumentVersionRecord.id == version_id)
            .values(status=status, error=error)
        )

    async def activate(self, version_id: int) -> None:
        document_id = (
            await self._session.execute(
                select(DocumentVersionRecord.document_id).where(
                    DocumentVersionRecord.id == version_id
                )
            )
        ).scalar_one()
        # Сначала снять флаг с остальных: уникальный индекс проверяется после каждого запроса.
        await self._session.execute(
            update(DocumentVersionRecord)
            .where(
                DocumentVersionRecord.document_id == document_id,
                DocumentVersionRecord.id != version_id,
            )
            .values(is_active=False)
        )
        await self._session.execute(
            update(DocumentVersionRecord)
            .where(DocumentVersionRecord.id == version_id)
            .values(is_active=True)
        )

    async def active_ids(self) -> list[int]:
        ids = await self._session.scalars(
            select(DocumentVersionRecord.id)
            .where(DocumentVersionRecord.is_active)
            .order_by(DocumentVersionRecord.id)
        )
        return list(ids)


class SqlChunkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def replace(self, version_id: int, chunks: Sequence[IndexedChunk]) -> None:
        # Повтор индексации перезаписывает фрагменты версии, а не добавляет к старым.
        await self._session.execute(delete(ChunkRecord).where(ChunkRecord.version_id == version_id))
        self._session.add_all(
            ChunkRecord(
                version_id=version_id,
                chunk_index=item.chunk.index,
                section_path=item.chunk.section_path,
                page=item.chunk.page,
                text_hash=hashlib.sha256(item.chunk.text.encode()).hexdigest(),
                qdrant_id=item.point_id,
            )
            for item in chunks
        )


class SqlKnowledgeUnitOfWork(SqlAlchemyUnitOfWork):
    documents: SqlDocumentRepository
    versions: SqlVersionRepository
    chunks: SqlChunkRepository

    async def __aenter__(self) -> Self:
        await super().__aenter__()
        self.documents = SqlDocumentRepository(self.session)
        self.versions = SqlVersionRepository(self.session)
        self.chunks = SqlChunkRepository(self.session)
        return self
