"""HTTP-адаптер модуля: переводит запросы в вызовы IdentityService. В хранилище не ходит."""

from collections.abc import Awaitable, Callable
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel

from chartroom.identity.domain import Role, User
from chartroom.identity.service import IdentityService

router = APIRouter(prefix="/auth", tags=["auth"])
_bearer = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_identity_service(request: Request) -> IdentityService:
    service: IdentityService = request.app.state.container.identity
    return service


IdentityServiceDep = Annotated[IdentityService, Depends(get_identity_service)]


async def get_current_user(
    token: Annotated[str, Depends(_bearer)], service: IdentityServiceDep
) -> User:
    return await service.authenticate(token)


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(minimum: Role) -> Callable[[User], Awaitable[User]]:
    async def dependency(user: CurrentUser) -> User:
        user.ensure_role(minimum)
        return user

    return dependency


def limit_per_client(policy: str) -> Callable[[Request], Awaitable[None]]:
    """Лимит по IP клиента — для эндпойнтов до входа. За прокси нужен его адрес в request.client."""

    async def dependency(request: Request) -> None:
        host = request.client.host if request.client else "unknown"
        await request.app.state.container.limiter.hit(policy, host)

    return dependency


def limit_per_user(policy: str) -> Callable[[Request, User], Awaitable[None]]:
    async def dependency(request: Request, user: CurrentUser) -> None:
        await request.app.state.container.limiter.hit(policy, f"user:{user.id}")

    return dependency


AdminUser = Annotated[User, Depends(require_role(Role.ADMIN))]
OfficerUser = Annotated[User, Depends(require_role(Role.OFFICER))]


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"


@router.post("/login", dependencies=[Depends(limit_per_client("login"))])
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()], service: IdentityServiceDep
) -> TokenResponse:
    """`username` — это email (OAuth2 password flow: так работает Authorize в Swagger)."""
    return TokenResponse(access_token=await service.login(form.username, form.password))
