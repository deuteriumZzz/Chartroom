import asyncio

from celery import Celery
from kombu.exceptions import OperationalError

from chartroom.shared.errors import ServiceUnavailableError

# Имя задачи — контракт между API (кто ставит) и worker-ом (кто выполняет).
INDEX_TASK = "chartroom.index_document_version"


class CeleryIndexingQueue:
    def __init__(self, app: Celery) -> None:
        self._app = app

    async def enqueue(self, version_id: int) -> None:
        try:
            # send_task блокирует поток на время записи в брокер — уводим его из event loop.
            await asyncio.to_thread(self._app.send_task, INDEX_TASK, args=[version_id])
        except OperationalError as e:
            raise ServiceUnavailableError("Indexing queue is unavailable") from e


def build_celery_producer(redis_url: str) -> Celery:
    app = Celery("chartroom", broker=redis_url)
    # Брокер недоступен — загрузка быстро получает 503, а не висит на повторных подключениях.
    app.conf.broker_connection_timeout = 3
    app.conf.task_publish_retry_policy = {
        "max_retries": 2,
        "interval_start": 0,
        "interval_step": 0.5,
    }
    return app
