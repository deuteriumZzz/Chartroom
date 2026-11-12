from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from chartroom.agent import api as agent_api
from chartroom.bootstrap import Container, build_container
from chartroom.identity import api as identity_api
from chartroom.knowledge import api as knowledge_api
from chartroom.qa import api as qa_api
from chartroom.reports import api as reports_api
from chartroom.shared.config import get_settings
from chartroom.shared.errors import (
    AuthenticationError,
    ConflictError,
    DomainError,
    InvalidInputError,
    NotFoundError,
    PermissionDeniedError,
    ServiceUnavailableError,
)

# Новый модуль добавляет ошибки-наследники — этот маппинг менять не нужно.
# Порядок важен: DomainError последним ловит всё, что не попало в категории выше.
_STATUS_BY_ERROR: dict[type[DomainError], int] = {
    AuthenticationError: 401,
    PermissionDeniedError: 403,
    NotFoundError: 404,
    ConflictError: 409,
    InvalidInputError: 422,
    DomainError: 400,
}


async def _domain_error_handler(_: Request, exc: Exception) -> JSONResponse:
    status = next(s for cls, s in _STATUS_BY_ERROR.items() if isinstance(exc, cls))
    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
    return JSONResponse({"detail": str(exc)}, status_code=status, headers=headers)


async def _service_unavailable_handler(_: Request, exc: Exception) -> JSONResponse:
    # Внешний сервис временно недоступен: клиент может повторить запрос.
    return JSONResponse({"detail": str(exc)}, status_code=503, headers={"Retry-After": "30"})


def create_app(container: Container | None = None) -> FastAPI:
    deps = container or build_container(get_settings())

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await deps.aclose()

    app = FastAPI(title="Chartroom", version="0.1.0", lifespan=lifespan)
    app.state.container = deps
    app.add_exception_handler(DomainError, _domain_error_handler)
    app.add_exception_handler(ServiceUnavailableError, _service_unavailable_handler)
    app.include_router(identity_api.router)
    app.include_router(knowledge_api.router)
    app.include_router(qa_api.router)
    app.include_router(reports_api.router)
    app.include_router(agent_api.router)

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
