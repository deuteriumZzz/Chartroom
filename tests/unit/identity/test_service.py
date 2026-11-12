from datetime import timedelta

import pytest

from chartroom.identity.adapters.tokens import JwtTokenService
from chartroom.identity.domain import (
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    InvalidEmailError,
    InvalidTokenError,
    Role,
    User,
    WeakPasswordError,
)
from chartroom.identity.service import IdentityService
from tests.fakes import FakePasswordHasher, InMemoryIdentityUnitOfWork

TOKENS = JwtTokenService("unit-test-secret-that-is-long-enough-0123456789", timedelta(minutes=5))


@pytest.fixture
def store() -> dict[int, User]:
    return {}


@pytest.fixture
def service(store: dict[int, User]) -> IdentityService:
    return IdentityService(lambda: InMemoryIdentityUnitOfWork(store), FakePasswordHasher(), TOKENS)


async def test_register_normalizes_email_and_persists(
    service: IdentityService, store: dict[int, User]
) -> None:
    user = await service.register(" Officer@Ship.test ", "s3cret-pass", Role.OFFICER)
    assert user.email == "officer@ship.test"
    assert store[user.id] == user


async def test_register_rejects_duplicate_email(service: IdentityService) -> None:
    await service.register("a@ship.test", "s3cret-pass", Role.OFFICER)
    with pytest.raises(EmailAlreadyRegisteredError):
        await service.register("A@ship.test", "other-pass", Role.ADMIN)


@pytest.mark.parametrize(
    ("email", "password", "error"),
    [("bad-email", "s3cret-pass", InvalidEmailError), ("a@ship.test", "short", WeakPasswordError)],
)
async def test_register_validates_input_before_saving(
    service: IdentityService,
    store: dict[int, User],
    email: str,
    password: str,
    error: type[Exception],
) -> None:
    with pytest.raises(error):
        await service.register(email, password, Role.OFFICER)
    assert store == {}


async def test_login_returns_token_that_authenticates_user(service: IdentityService) -> None:
    user = await service.register("a@ship.test", "s3cret-pass", Role.CAPTAIN)
    token = await service.login("A@SHIP.test", "s3cret-pass")
    assert await service.authenticate(token) == user


@pytest.mark.parametrize(
    ("email", "password"), [("a@ship.test", "wrong"), ("nobody@ship.test", "s3cret-pass")]
)
async def test_login_rejects_bad_credentials(
    service: IdentityService, email: str, password: str
) -> None:
    await service.register("a@ship.test", "s3cret-pass", Role.OFFICER)
    with pytest.raises(InvalidCredentialsError):
        await service.login(email, password)


async def test_authenticate_rejects_token_of_missing_user(service: IdentityService) -> None:
    with pytest.raises(InvalidTokenError):
        await service.authenticate(TOKENS.issue(user_id=999))


async def test_user_is_found_by_email_ignoring_case(service: IdentityService) -> None:
    from chartroom.identity.domain import UserNotFoundError

    user = await service.register("eval@ship.test", "s3cret-pass", Role.ADMIN)
    assert await service.user_by_email(" EVAL@ship.test ") == user
    with pytest.raises(UserNotFoundError):
        await service.user_by_email("nobody@ship.test")
