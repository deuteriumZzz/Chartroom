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
from chartroom.knowledge.adapters.gemini import GeminiEmbedder, UnconfiguredQueryEmbedder
from chartroom.knowledge.adapters.parsers import (
    DocxParser,
    MarkdownParser,
    PdfParser,
    PlainTextParser,
)
from chartroom.knowledge.adapters.persistence import SqlKnowledgeUnitOfWork
from chartroom.knowledge.adapters.qdrant import QdrantChunkIndex
from chartroom.knowledge.adapters.queue import CeleryIndexingQueue, build_celery_producer
from chartroom.knowledge.domain.models import DocumentFormat
from chartroom.knowledge.ports import IndexingQueue, QueryEmbedder
from chartroom.knowledge.service import ChunkRetriever, DocumentChunker, DocumentLibrary, Indexer
from chartroom.qa.adapters.gemini import GeminiAnswerGenerator, UnconfiguredAnswerGenerator
from chartroom.qa.adapters.knowledge import KnowledgePassageRetriever
from chartroom.qa.adapters.persistence import SqlQaUnitOfWork
from chartroom.qa.domain import RefusalPolicy
from chartroom.qa.ports import AnswerGenerator, PassageRetriever
from chartroom.qa.service import QuestionService
from chartroom.shared.config import Settings


@dataclass(frozen=True)
class Container:
    identity: IdentityService
    library: DocumentLibrary
    questions: QuestionService
    engine: AsyncEngine | None = None  # None, если фабрику сессий передали снаружи (тесты)
    qdrant: AsyncQdrantClient | None = None  # None, если поиск подменили (тесты)

    async def aclose(self) -> None:
        if self.qdrant is not None:
            await self.qdrant.close()
        if self.engine is not None:
            await self.engine.dispose()


def build_container(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    queue: IndexingQueue | None = None,
    retriever: PassageRetriever | None = None,
    generator: AnswerGenerator | None = None,
) -> Container:
    """Аргументы после settings подменяют тесты; в работе всё строится из настроек."""
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
    library = DocumentLibrary(
        uow_factory=lambda: SqlKnowledgeUnitOfWork(sessions),
        queue=queue or CeleryIndexingQueue(build_celery_producer(settings.redis_url)),
    )
    gemini = _gemini_client(settings)
    # Без ключа API стартует: загрузка работает, а поиск и генерация отвечают 503.
    embedder: QueryEmbedder = UnconfiguredQueryEmbedder()
    default_generator: AnswerGenerator = UnconfiguredAnswerGenerator()
    if gemini is not None:
        embedder = GeminiEmbedder(gemini, settings.embedding_model, settings.embedding_dimensions)
        default_generator = GeminiAnswerGenerator(gemini, settings.generation_models)

    qdrant = None
    if retriever is None:
        qdrant = _qdrant_client(settings)
        chunks = ChunkRetriever(
            uow_factory=lambda: SqlKnowledgeUnitOfWork(sessions),
            embedder=embedder,
            index=QdrantChunkIndex(qdrant, settings.qdrant_collection),
        )
        retriever = KnowledgePassageRetriever(chunks)
    questions = QuestionService(
        retriever=retriever,
        generator=generator or default_generator,
        policy=RefusalPolicy(settings.refusal_min_similarity),
        uow_factory=lambda: SqlQaUnitOfWork(sessions),
    )
    return Container(
        identity=identity, library=library, questions=questions, engine=engine, qdrant=qdrant
    )


def _qdrant_client(settings: Settings) -> AsyncQdrantClient:
    # Версии клиента и сервера закреплены вместе (uv.lock и docker-compose.yml): проверка
    # совместимости при каждом старте — лишний сетевой вызов.
    return AsyncQdrantClient(url=settings.qdrant_url, check_compatibility=False)


def _gemini_client(settings: Settings) -> genai.Client | None:
    key = settings.gemini_api_key.get_secret_value()
    if not key:
        return None
    # Таймаут и повторы с экспоненциальной паузой на каждый вызов LLM и эмбеддингов.
    http = types.HttpOptions(timeout=30_000, retry_options=types.HttpRetryOptions(attempts=3))
    return genai.Client(api_key=key, http_options=http)


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
    qdrant = _qdrant_client(settings)
    gemini = _gemini_client(settings)
    if gemini is None:
        raise RuntimeError("GEMINI_API_KEY is required to run the indexing worker")
    indexer = Indexer(
        uow_factory=lambda: SqlKnowledgeUnitOfWork(sessions),
        chunker=build_document_chunker(),
        embedder=GeminiEmbedder(gemini, settings.embedding_model, settings.embedding_dimensions),
        index=QdrantChunkIndex(qdrant, settings.qdrant_collection),
    )
    return WorkerContainer(indexer=indexer, engine=engine, qdrant=qdrant)
