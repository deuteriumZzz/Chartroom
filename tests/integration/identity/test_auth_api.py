from collections.abc import AsyncIterator
from typing import Annotated

import pytest
from fastapi import Depends
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from chartroom.bootstrap import Container, build_container
from chartroom.identity.api import require_role
from chartroom.identity.domain import Role, User
from chartroom.main import create_app
from chartroom.shared.config import get_settings

PASSWORD = "s3cret-pass"


@pytest.fixture
def container(session_factory: async_sessionmaker[AsyncSession]) -> Container:
    return build_container(get_settings(), session_factory)


@pytest.fixture
async def client(container: Container) -> AsyncIterator[AsyncClient]:
    app = create_app(container)

    # Пробные маршруты живут только в этом экземпляре приложения, в боевое не попадают.
    @app.get("/probe/officer")
    async def officer(user: Annotated[User, Depends(require_role(Role.OFFICER))]) -> str:
        return user.email

    @app.get("/probe/admin")
    async def admin(user: Annotated[User, Depends(require_role(Role.ADMIN))]) -> str:
        return user.email

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _auth_header(client: AsyncClient, email: str) -> dict[str, str]:
    r = await client.post("/auth/login", data={"username": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    assert r.json()["token_type"] == "bearer"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_login_and_role_based_access(client: AsyncClient, container: Container) -> None:
    await container.identity.register("off@ship.test", PASSWORD, Role.OFFICER)
    await container.identity.register("adm@ship.test", PASSWORD, Role.ADMIN)
    officer = await _auth_header(client, "OFF@ship.test")
    admin = await _auth_header(client, "adm@ship.test")

    assert (await client.get("/probe/officer", headers=officer)).json() == "off@ship.test"
    forbidden = await client.get("/probe/admin", headers=officer)
    assert (forbidden.status_code, forbidden.json()) == (403, {"detail": "Insufficient role"})
    assert (await client.get("/probe/admin", headers=admin)).status_code == 200
    assert (await client.get("/probe/officer", headers=admin)).status_code == 200


async def test_bad_credentials_get_uniform_401(client: AsyncClient, container: Container) -> None:
    await container.identity.register("a@ship.test", PASSWORD, Role.OFFICER)
    for email, password in [("a@ship.test", "wrong"), ("nobody@ship.test", PASSWORD)]:
        r = await client.post("/auth/login", data={"username": email, "password": password})
        assert r.status_code == 401
        assert r.json() == {"detail": "Incorrect email or password"}
        assert r.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer garbage"}])
async def test_protected_route_requires_valid_token(
    client: AsyncClient, headers: dict[str, str]
) -> None:
    assert (await client.get("/probe/officer", headers=headers)).status_code == 401


async def test_passwords_and_tokens_never_reach_the_logs(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("DEBUG")
    await client.post(
        "/auth/login", data={"username": "ghost@ship.test", "password": "Sup3r-secret-pw"}
    )
    assert "Sup3r-secret-pw" not in caplog.text
