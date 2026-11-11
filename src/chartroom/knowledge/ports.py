"""Что модулю knowledge нужно от внешнего мира."""

from typing import Protocol

from chartroom.knowledge.domain.models import Block


class DocumentParser(Protocol):
    def parse(self, content: bytes) -> list[Block]:
        """Raises InvalidDocumentError, если содержимое не разбирается."""
        ...
