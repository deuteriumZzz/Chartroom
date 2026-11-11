"""Celery worker фоновой индексации: celery -A chartroom.worker worker."""

import asyncio
from collections.abc import Awaitable, Callable

from celery import Celery
from celery.exceptions import SoftTimeLimitExceeded

from chartroom.bootstrap import build_worker_container
from chartroom.knowledge.adapters.queue import INDEX_TASK
from chartroom.knowledge.service import Indexer
from chartroom.shared.config import Settings, get_settings
from chartroom.shared.errors import ServiceUnavailableError


def require_embedding_key(settings: Settings) -> None:
    if not settings.gemini_api_key.get_secret_value():
        raise RuntimeError("GEMINI_API_KEY is required to run the indexing worker")


# Проверка при импорте, а не в сигнале worker_init: Celery глотает исключения обработчиков
# сигналов, и worker стартовал бы без ключа. Теперь `celery -A chartroom.worker` без ключа падает.
require_embedding_key(get_settings())

app = Celery("chartroom", broker=get_settings().redis_url)
app.conf.update(
    task_acks_late=True,  # задача подтверждается после выполнения: падение worker-а её не теряет
    worker_prefetch_multiplier=1,
)


async def _with_indexer(action: Callable[[Indexer], Awaitable[None]]) -> None:
    container = build_worker_container(get_settings())
    try:
        await action(container.indexer)
    finally:
        await container.aclose()


@app.task(
    name=INDEX_TASK,
    autoretry_for=(ServiceUnavailableError,),
    retry_backoff=True,
    max_retries=3,
    soft_time_limit=120,
    time_limit=180,
    ignore_result=True,
)
def index_document_version(version_id: int) -> None:
    try:
        asyncio.run(_with_indexer(lambda indexer: indexer.index(version_id)))
    except SoftTimeLimitExceeded:
        timed_out = "Indexing timed out"
        asyncio.run(_with_indexer(lambda indexer: indexer.mark_failed(version_id, timed_out)))
        raise
