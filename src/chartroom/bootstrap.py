"""Точка сборки (composition root): единственное место, где порты связываются с адаптерами."""

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from chartroom.identity.adapters.passwords import Argon2PasswordHasher
from chartroom.identity.adapters.persistence import SqlIdentityUnitOfWork
from chartroom.identity.adapters.tokens import JwtTokenService
from chartroom.identity.service import IdentityService
from chartroom.knowledge.adapters.parsers import (
    DocxParser,
    MarkdownParser,
    PdfParser,
    PlainTextParser,
)
from chartroom.knowledge.domain.models import DocumentFormat
from chartroom.knowledge.service import DocumentChunker
from chartroom.shared.config import Settings


@dataclass(frozen=True)
class Container:
    identity: IdentityService
    engine: AsyncEngine | None = None  # None, если фабрику сессий передали снаружи (тесты)

    async def aclose(self) -> None:
        if self.engine is not None:
            await self.engine.dispose()


def build_container(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession] | None = None
) -> Container:
    engine = None
    if session_factory is None:
        engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
    sessions = session_factory

    identity = IdentityService(
        uow_factory=lambda: SqlIdentityUnitOfWork(sessions),
        hasher=Argon2PasswordHasher(),
        tokens=JwtTokenService(
            settings.jwt_secret.get_secret_value(), timedelta(minutes=settings.jwt_ttl_minutes)
        ),
    )
    return Container(identity=identity, engine=engine)


def build_document_chunker() -> DocumentChunker:
    return DocumentChunker(
        {
            DocumentFormat.PDF: PdfParser(),
            DocumentFormat.DOCX: DocxParser(),
            DocumentFormat.MARKDOWN: MarkdownParser(),
            DocumentFormat.TEXT: PlainTextParser(),
        }
    )
