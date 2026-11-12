"""In-memory реализации портов для unit-тестов. Совпадение поведения с SQL-адаптерами
проверяют контрактные тесты в tests/integration/*/test_unit_of_work_contract.py."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field, fields, replace
from datetime import UTC, datetime
from typing import Self

from chartroom.identity.domain import EmailAlreadyRegisteredError, Role, User
from chartroom.knowledge.domain.indexing import IndexedChunk, RetrievedChunk
from chartroom.knowledge.domain.models import (
    Document,
    DocumentAlreadyExistsError,
    DocumentUpload,
    DocumentVersion,
    DuplicateFileError,
    DuplicateVersionError,
    IndexingStatus,
)
from chartroom.qa.domain import (
    Feedback,
    GeneratedAnswer,
    LoggedQuery,
    Passage,
    QueryEntry,
)
from chartroom.reports.domain import (
    Report,
    ReportData,
    ReportStatus,
    ReportTemplate,
)
from chartroom.shared.errors import ServiceUnavailableError
from chartroom.shared.language import Language
from chartroom.shared.schema import Issue, Schema
from chartroom.shared.sparse import SparseVector


class InMemoryUserRepository:
    def __init__(self, users: dict[int, User]) -> None:
        self._users = users

    async def get(self, user_id: int) -> User | None:
        return self._users.get(user_id)

    async def get_by_email(self, email: str) -> User | None:
        return next((u for u in self._users.values() if u.email == email), None)

    async def add(self, email: str, password_hash: str, role: Role) -> User:
        if await self.get_by_email(email):
            raise EmailAlreadyRegisteredError
        user = User(
            id=max(self._users, default=0) + 1, email=email, password_hash=password_hash, role=role
        )
        self._users[user.id] = user
        return user


class InMemoryIdentityUnitOfWork:
    """Та же транзакционность, что у SQL: изменения видны снаружи только после commit()."""

    users: InMemoryUserRepository

    def __init__(self, store: dict[int, User]) -> None:
        self._store = store

    async def __aenter__(self) -> Self:
        self._pending = dict(self._store)
        self.users = InMemoryUserRepository(self._pending)
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def commit(self) -> None:
        self._store.update(self._pending)


class FakePasswordHasher:
    """Без argon2: unit-тесты сервиса проверяют сценарии, а не криптографию."""

    async def hash(self, password: str) -> str:
        return f"hashed:{password}"

    async def verify(self, password: str, password_hash: str | None) -> bool:
        return password_hash == f"hashed:{password}"


@dataclass
class KnowledgeStore:
    documents: dict[int, Document] = field(default_factory=dict)
    versions: dict[int, DocumentVersion] = field(default_factory=dict)
    contents: dict[int, bytes] = field(default_factory=dict)
    chunks: dict[int, list[IndexedChunk]] = field(default_factory=dict)

    def copy(self) -> "KnowledgeStore":
        return KnowledgeStore(
            dict(self.documents),
            dict(self.versions),
            dict(self.contents),
            {version_id: list(chunks) for version_id, chunks in self.chunks.items()},
        )


class InMemoryDocumentRepository:
    def __init__(self, store: KnowledgeStore) -> None:
        self._store = store

    async def get(self, document_id: int) -> Document | None:
        return self._store.documents.get(document_id)

    async def find(self, title: str, language: Language) -> Document | None:
        key = title.casefold()
        documents = self._store.documents.values()
        return next(
            (d for d in documents if (d.title.casefold(), d.language) == (key, language)), None
        )

    async def add(self, title: str, language: Language) -> Document:
        if await self.find(title, language):
            raise DocumentAlreadyExistsError
        document = Document(
            id=max(self._store.documents, default=0) + 1, title=title, language=language
        )
        self._store.documents[document.id] = document
        return document


class InMemoryVersionRepository:
    def __init__(self, store: KnowledgeStore) -> None:
        self._store = store

    async def get(self, version_id: int) -> DocumentVersion | None:
        return self._store.versions.get(version_id)

    async def list_for(self, document_id: int) -> list[DocumentVersion]:
        versions = self._store.versions.values()
        return sorted((v for v in versions if v.document_id == document_id), key=lambda v: v.id)

    async def add(self, document_id: int, upload: DocumentUpload, checksum: str) -> DocumentVersion:
        existing = await self.list_for(document_id)
        if any(v.label == upload.label for v in existing):
            raise DuplicateVersionError
        if any(v.checksum == checksum for v in existing):
            raise DuplicateFileError
        version = DocumentVersion(
            id=max(self._store.versions, default=0) + 1,
            document_id=document_id,
            label=upload.label,
            issued_on=upload.issued_on,
            filename=upload.filename,
            checksum=checksum,
            status=IndexingStatus.PENDING,
            is_active=False,
            uploaded_at=datetime.now(UTC),
        )
        self._store.versions[version.id] = version
        self._store.contents[version.id] = upload.content
        return version

    async def get_content(self, version_id: int) -> bytes:
        return self._store.contents[version_id]

    async def set_status(
        self, version_id: int, status: IndexingStatus, error: str | None = None
    ) -> None:
        self._store.versions[version_id] = replace(
            self._store.versions[version_id], status=status, error=error
        )

    async def activate(self, version_id: int) -> None:
        document_id = self._store.versions[version_id].document_id
        for version in await self.list_for(document_id):
            self._store.versions[version.id] = replace(version, is_active=version.id == version_id)

    async def active_ids(self) -> list[int]:
        return sorted(v.id for v in self._store.versions.values() if v.is_active)


class InMemoryChunkRepository:
    def __init__(self, store: KnowledgeStore) -> None:
        self._store = store

    async def replace(self, version_id: int, chunks: Sequence[IndexedChunk]) -> None:
        self._store.chunks[version_id] = list(chunks)


class InMemoryKnowledgeUnitOfWork:
    """Та же транзакционность, что у SQL: изменения видны снаружи только после commit()."""

    documents: InMemoryDocumentRepository
    versions: InMemoryVersionRepository
    chunks: InMemoryChunkRepository

    def __init__(self, store: KnowledgeStore) -> None:
        self._store = store

    async def __aenter__(self) -> Self:
        self._pending = self._store.copy()
        self.documents = InMemoryDocumentRepository(self._pending)
        self.versions = InMemoryVersionRepository(self._pending)
        self.chunks = InMemoryChunkRepository(self._pending)
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def commit(self) -> None:
        committed = self._pending.copy()
        for store_field in fields(KnowledgeStore):
            setattr(self._store, store_field.name, getattr(committed, store_field.name))


class FakeEmbedder:
    dimensions = 3

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.queries: list[str] = []
        self.unavailable = False

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if self.unavailable:
            raise ServiceUnavailableError("Embedding provider is unavailable")
        self.calls.append(list(texts))
        return [[float(len(text)), 1.0, 0.0] for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return [float(len(text)), 1.0, 0.0]


class InMemoryChunkIndex:
    def __init__(self) -> None:
        self.dimensions: int | None = None
        self.points: dict[uuid.UUID, IndexedChunk] = {}

    async def ensure_collection(self, dimensions: int) -> None:
        self.dimensions = dimensions

    async def upsert(self, chunks: Sequence[IndexedChunk]) -> None:
        self.points.update((chunk.point_id, chunk) for chunk in chunks)

    async def search(
        self,
        dense: Sequence[float],
        sparse: SparseVector,
        version_ids: Sequence[int],
        limit: int,
    ) -> list[RetrievedChunk]:
        """Упрощённое ранжирование по числу общих терминов; настоящее слияние RRF — в Qdrant.
        Сходство — доля терминов вопроса, найденных во фрагменте."""
        candidates = [p for p in self.points.values() if p.version_id in version_ids]
        scored = [(len(set(p.sparse.indices) & set(sparse.indices)), p) for p in candidates]
        scored.sort(key=lambda item: (-item[0], item[1].version_id, item[1].chunk.index))
        return [
            RetrievedChunk(
                p.document_id,
                p.version_id,
                p.title,
                p.language,
                p.chunk.section_path,
                p.chunk.page,
                p.chunk.index,
                p.chunk.text,
                float(score),
                score / max(len(sparse.indices), 1),
            )
            for score, p in scored[:limit]
        ]


class RecordingQueue:
    def __init__(self) -> None:
        self.enqueued: list[int] = []

    async def enqueue(self, version_id: int) -> None:
        self.enqueued.append(version_id)


class StaticPassageRetriever:
    """Порт PassageRetriever для тестов qa: заданные фрагменты и журнал вызовов."""

    def __init__(self, passages: list[Passage]) -> None:
        self.passages = passages
        self.calls: list[tuple[str, int]] = []

    async def retrieve(self, question: str, limit: int) -> list[Passage]:
        self.calls.append((question, limit))
        return self.passages[:limit]


class ScriptedGenerator:
    """Порт AnswerGenerator для тестов: заранее заданный ответ модели и журнал вызовов."""

    prompt_version = "test.v1"

    def __init__(self, answer: GeneratedAnswer) -> None:
        self.answer = answer
        self.calls: list[tuple[str, Language, list[Passage]]] = []

    async def generate(
        self, question: str, language: Language, passages: Sequence[Passage]
    ) -> GeneratedAnswer:
        self.calls.append((question, language, list(passages)))
        return self.answer


@dataclass
class QaStore:
    queries: dict[int, LoggedQuery] = field(default_factory=dict)


class InMemoryQueryLog:
    def __init__(self, store: QaStore) -> None:
        self._store = store

    async def add(self, entry: QueryEntry) -> int:
        query_id = max(self._store.queries, default=0) + 1
        self._store.queries[query_id] = LoggedQuery(
            id=query_id,
            user_id=entry.user_id,
            question=entry.question,
            answer=entry.answer,
            latency_ms=entry.latency_ms,
            model=entry.model,
            prompt_version=entry.prompt_version,
            created_at=datetime.now(UTC),
            feedback=None,
        )
        return query_id

    async def get(self, query_id: int) -> LoggedQuery | None:
        return self._store.queries.get(query_id)

    async def list(self, user_id: int | None, limit: int, offset: int) -> list[LoggedQuery]:
        queries = sorted(self._store.queries.values(), key=lambda q: q.id, reverse=True)
        mine = [q for q in queries if user_id is None or q.user_id == user_id]
        return mine[offset : offset + limit]


class InMemoryFeedbackRepository:
    def __init__(self, store: QaStore) -> None:
        self._store = store

    async def save(self, query_id: int, feedback: Feedback) -> None:
        self._store.queries[query_id] = replace(self._store.queries[query_id], feedback=feedback)


class InMemoryQaUnitOfWork:
    """Та же транзакционность, что у SQL: изменения видны снаружи только после commit()."""

    queries: InMemoryQueryLog
    feedback: InMemoryFeedbackRepository

    def __init__(self, store: QaStore) -> None:
        self._store = store

    async def __aenter__(self) -> Self:
        self._pending = QaStore(dict(self._store.queries))
        self.queries = InMemoryQueryLog(self._pending)
        self.feedback = InMemoryFeedbackRepository(self._pending)
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def commit(self) -> None:
        self._store.queries = dict(self._pending.queries)


@dataclass
class ReportsStore:
    templates: dict[int, ReportTemplate] = field(default_factory=dict)
    reports: dict[int, Report] = field(default_factory=dict)

    def copy(self) -> "ReportsStore":
        return ReportsStore(dict(self.templates), dict(self.reports))


class InMemoryTemplateRepository:
    def __init__(self, store: ReportsStore) -> None:
        self._store = store

    async def get(self, template_id: int) -> ReportTemplate:
        return self._store.templates[template_id]

    async def latest(self, name: str) -> ReportTemplate | None:
        versions = [t for t in self._store.templates.values() if t.name == name]
        return max(versions, key=lambda t: t.version, default=None)

    async def list_latest(self) -> list[ReportTemplate]:
        names = sorted({t.name for t in self._store.templates.values()})
        return [t for name in names if (t := await self.latest(name)) is not None]

    async def add(self, name: str, title: str, schema: Schema) -> ReportTemplate:
        current = await self.latest(name)
        template = ReportTemplate(
            max(self._store.templates, default=0) + 1,
            name,
            title,
            schema,
            (current.version if current else 0) + 1,
        )
        self._store.templates[template.id] = template
        return template


class InMemoryReportRepository:
    def __init__(self, store: ReportsStore) -> None:
        self._store = store

    async def get(self, report_id: int) -> Report | None:
        return self._store.reports.get(report_id)

    async def add(
        self,
        template_id: int,
        user_id: int,
        source_text: str,
        data: ReportData,
        status: ReportStatus,
        issues: tuple[Issue, ...],
    ) -> Report:
        report = Report(
            max(self._store.reports, default=0) + 1,
            template_id,
            user_id,
            source_text,
            data,
            status,
            issues,
            datetime.now(UTC),
        )
        self._store.reports[report.id] = report
        return report

    async def update(
        self, report_id: int, data: ReportData, status: ReportStatus, issues: tuple[Issue, ...]
    ) -> Report:
        report = replace(self._store.reports[report_id], data=data, status=status, issues=issues)
        self._store.reports[report_id] = report
        return report

    async def list(
        self,
        user_id: int | None,
        status: ReportStatus | None,
        template_name: str | None,
        limit: int,
    ) -> list[Report]:
        names = {t.id: t.name for t in self._store.templates.values()}
        reports = sorted(self._store.reports.values(), key=lambda r: r.id, reverse=True)
        return [
            r
            for r in reports
            if (user_id is None or r.user_id == user_id)
            and (status is None or r.status is status)
            and (template_name is None or names[r.template_id] == template_name)
        ][:limit]


class InMemoryReportsUnitOfWork:
    """Та же транзакционность, что у SQL: изменения видны снаружи только после commit()."""

    templates: InMemoryTemplateRepository
    reports: InMemoryReportRepository

    def __init__(self, store: ReportsStore) -> None:
        self._store = store

    async def __aenter__(self) -> Self:
        self._pending = self._store.copy()
        self.templates = InMemoryTemplateRepository(self._pending)
        self.reports = InMemoryReportRepository(self._pending)
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def commit(self) -> None:
        committed = self._pending.copy()
        self._store.templates, self._store.reports = committed.templates, committed.reports


class ScriptedExtractor:
    """Порт ReportExtractor для тестов: заданные поля и журнал вызовов."""

    def __init__(self, data: ReportData) -> None:
        self.data = data
        self.calls: list[tuple[str, str]] = []

    async def extract(self, text: str, template: ReportTemplate) -> ReportData:
        self.calls.append((text, template.name))
        return dict(self.data)
