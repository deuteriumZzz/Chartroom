"""Точка сборки (composition root): единственное место, где порты связываются с адаптерами."""

from dataclasses import dataclass
from datetime import timedelta

from google import genai
from google.genai import types
from qdrant_client import AsyncQdrantClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from chartroom.identity.adapters.passwords import Argon2PasswordHasher
from chartroom.identity.adapters.persistence import SqlIdentityUnitOfWork
from chartroom.identity.adapters.tokens import JwtTokenService
from chartroom.identity.service import IdentityService
from chartroom.knowledge.adapters.gemini import GeminiEmbedder
from chartroom.knowledge.adapters.parsers import (
    DocxParser,
    MarkdownParser,
    PdfParser,
    PlainTextParser,
)
from chartroom.knowledge.adapters.persistence import SqlKnowledgeUnitOfWork
from chartroom.knowledge.adapters.qdrant import QdrantChunkIndex
from chartroom.knowledge.domain.models import DocumentFormat
from chartroom.knowledge.service import DocumentChunker, Indexer
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


@dataclass(frozen=True)
class WorkerContainer:
    indexer: Indexer
    engine: AsyncEngine
    qdrant: AsyncQdrantClient

    async def aclose(self) -> None:
        await self.qdrant.close()
        await self.engine.dispose()


def build_worker_container(settings: Settings) -> WorkerContainer:
    # Каждая задача Celery запускает свой event loop (asyncio.run). Пул соединений, привязанный
    # к прошлому loop, сломался бы, поэтому worker работает без пула.
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    qdrant = AsyncQdrantClient(url=settings.qdrant_url)
    gemini = genai.Client(
        api_key=settings.gemini_api_key.get_secret_value(),
        http_options=types.HttpOptions(timeout=30_000),
    )
    indexer = Indexer(
        uow_factory=lambda: SqlKnowledgeUnitOfWork(sessions),
        chunker=build_document_chunker(),
        embedder=GeminiEmbedder(gemini, settings.embedding_model, settings.embedding_dimensions),
        index=QdrantChunkIndex(qdrant, settings.qdrant_collection),
    )
    return WorkerContainer(indexer=indexer, engine=engine, qdrant=qdrant)
