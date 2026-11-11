"""HTTP-адаптер модуля knowledge: загрузка документов и статус индексации."""

from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from pydantic import BaseModel, ConfigDict

from chartroom.identity.api import AdminUser
from chartroom.knowledge.domain.models import (
    MAX_UPLOAD_BYTES,
    DocumentUpload,
    IndexingStatus,
    Language,
)
from chartroom.knowledge.service import DocumentLibrary

router = APIRouter(prefix="/documents", tags=["documents"])


def get_library(request: Request) -> DocumentLibrary:
    library: DocumentLibrary = request.app.state.container.library
    return library


LibraryDep = Annotated[DocumentLibrary, Depends(get_library)]


class VersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    label: str
    issued_on: date
    filename: str
    status: IndexingStatus
    is_active: bool
    uploaded_at: datetime
    error: str | None


class UploadResponse(BaseModel):
    document_id: int
    version: VersionResponse


class DocumentStatusResponse(BaseModel):
    id: int
    title: str
    language: Language
    versions: list[VersionResponse]


@router.post("", status_code=202)
async def upload_document(
    _: AdminUser,
    library: LibraryDep,
    file: UploadFile,
    title: Annotated[str, Form(max_length=300)],
    version: Annotated[str, Form(max_length=50)],
    language: Annotated[Language, Form()],
    issued_on: Annotated[date, Form()],
) -> UploadResponse:
    """Принимает файл и ставит его в очередь индексации. Статус — GET /documents/{id}/status.

    Новая версия существующего документа — та же загрузка с тем же названием и языком.
    """
    content = await file.read(MAX_UPLOAD_BYTES + 1)  # больше лимита не читаем
    upload = DocumentUpload(title, language, version, issued_on, file.filename or "", content)
    uploaded = await library.upload(upload)
    return UploadResponse(
        document_id=uploaded.document_id, version=VersionResponse.model_validate(uploaded)
    )


@router.get("/{document_id}/status")
async def document_status(
    document_id: int, _: AdminUser, library: LibraryDep
) -> DocumentStatusResponse:
    overview = await library.overview(document_id)
    return DocumentStatusResponse(
        id=overview.document.id,
        title=overview.document.title,
        language=overview.document.language,
        versions=[VersionResponse.model_validate(v) for v in overview.versions],
    )
