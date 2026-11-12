"""Мост к модулю knowledge: какая редакция документа действует."""

from typing import Any

from chartroom.knowledge.service import DocumentLibrary


class LibraryDocumentsReader:
    def __init__(self, library: DocumentLibrary) -> None:
        self._library = library

    async def active_version(self, title: str) -> dict[str, Any]:
        document, version = await self._library.active_version(title)
        return {
            "title": document.title,
            "language": document.language.value,
            "active_version": version.label if version else None,
            "issued_on": version.issued_on.isoformat() if version else None,
        }
