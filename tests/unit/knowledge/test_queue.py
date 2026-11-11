from typing import cast

import pytest
from celery import Celery
from kombu.exceptions import OperationalError

from chartroom.knowledge.adapters.queue import (
    INDEX_TASK,
    CeleryIndexingQueue,
    build_celery_producer,
)
from chartroom.shared.errors import ServiceUnavailableError


class StubCelery:
    def __init__(self, failure: Exception | None = None) -> None:
        self.sent: list[tuple[str, list[int]]] = []
        self._failure = failure

    def send_task(self, name: str, args: list[int]) -> None:
        if self._failure:
            raise self._failure
        self.sent.append((name, args))


async def test_enqueue_sends_index_task_by_name() -> None:
    app = StubCelery()
    await CeleryIndexingQueue(cast(Celery, app)).enqueue(42)
    assert app.sent == [(INDEX_TASK, [42])]


async def test_unavailable_broker_is_service_unavailable() -> None:
    queue = CeleryIndexingQueue(cast(Celery, StubCelery(OperationalError("redis is down"))))
    with pytest.raises(ServiceUnavailableError, match="Indexing queue is unavailable"):
        await queue.enqueue(42)


def test_producer_fails_fast_when_broker_is_down() -> None:
    app = build_celery_producer("redis://localhost:6379/0")
    assert app.conf.broker_connection_timeout == 3
    assert app.conf.task_publish_retry_policy["max_retries"] == 2
