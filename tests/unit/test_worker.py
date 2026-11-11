import pytest
from celery.exceptions import SoftTimeLimitExceeded
from pydantic import SecretStr

from chartroom import worker
from chartroom.bootstrap import build_worker_container
from chartroom.shared.config import Settings, get_settings


class FakeIndexer:
    def __init__(self, failure: BaseException | None = None) -> None:
        self.indexed: list[int] = []
        self.failed: list[tuple[int, str]] = []
        self._failure = failure

    async def index(self, version_id: int) -> None:
        if self._failure:
            raise self._failure
        self.indexed.append(version_id)

    async def mark_failed(self, version_id: int, reason: str) -> None:
        self.failed.append((version_id, reason))


class FakeContainer:
    def __init__(self, indexer: FakeIndexer) -> None:
        self.indexer = indexer
        self.closed = 0

    async def aclose(self) -> None:
        self.closed += 1


def _install(monkeypatch: pytest.MonkeyPatch, indexer: FakeIndexer) -> FakeContainer:
    container = FakeContainer(indexer)
    monkeypatch.setattr(worker, "build_worker_container", lambda _: container)
    return container


def test_task_indexes_version_and_releases_resources(monkeypatch: pytest.MonkeyPatch) -> None:
    indexer = FakeIndexer()
    container = _install(monkeypatch, indexer)
    worker.index_document_version.run(5)
    assert (indexer.indexed, container.closed) == ([5], 1)


def test_timeout_marks_version_failed_and_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    indexer = FakeIndexer(failure=SoftTimeLimitExceeded())
    container = _install(monkeypatch, indexer)
    with pytest.raises(SoftTimeLimitExceeded):
        worker.index_document_version.run(5)
    assert indexer.failed == [(5, "Indexing timed out")]
    assert container.closed == 2


def _settings(key: str) -> Settings:
    return get_settings().model_copy(update={"gemini_api_key": SecretStr(key)})


def test_worker_refuses_to_start_without_gemini_key() -> None:
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        worker.require_embedding_key(_settings(""))
    worker.require_embedding_key(_settings("test-key"))


async def test_worker_container_builds_without_network_and_closes() -> None:
    container = build_worker_container(_settings("test-key"))
    await container.aclose()


def test_worker_container_requires_gemini_key() -> None:
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        build_worker_container(_settings(""))
