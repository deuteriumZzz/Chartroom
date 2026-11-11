from datetime import timedelta

import jwt
import pytest

from chartroom.identity.adapters.passwords import Argon2PasswordHasher
from chartroom.identity.adapters.tokens import JwtTokenService
from chartroom.identity.domain import InvalidTokenError

SECRET = "unit-test-secret-that-is-long-enough-0123456789"


async def test_argon2_hash_and_verify() -> None:
    hasher = Argon2PasswordHasher()
    password_hash = await hasher.hash("correct horse")
    assert password_hash.startswith("$argon2id$")
    assert await hasher.verify("correct horse", password_hash)
    assert not await hasher.verify("wrong horse", password_hash)


async def test_argon2_verify_without_hash_is_false() -> None:
    assert not await Argon2PasswordHasher().verify("timing-equalizer", None)


def test_jwt_roundtrip() -> None:
    tokens = JwtTokenService(SECRET, timedelta(minutes=5))
    assert tokens.read_user_id(tokens.issue(42)) == 42


@pytest.mark.parametrize(
    "token",
    [
        pytest.param(JwtTokenService(SECRET, timedelta(seconds=-1)).issue(1), id="expired"),
        pytest.param(JwtTokenService("x" * 48, timedelta(minutes=5)).issue(1), id="wrong-secret"),
        pytest.param(
            jwt.encode({"sub": "1", "exp": 9999999999}, "", algorithm="none"), id="alg-none"
        ),
        pytest.param(jwt.encode({"sub": "1"}, SECRET, algorithm="HS256"), id="no-exp"),
        pytest.param(
            jwt.encode({"sub": "x", "exp": 9999999999}, SECRET, algorithm="HS256"), id="bad-sub"
        ),
        pytest.param("not-a-jwt", id="garbage"),
    ],
)
def test_jwt_rejects_invalid_tokens(token: str) -> None:
    with pytest.raises(InvalidTokenError):
        JwtTokenService(SECRET, timedelta(minutes=5)).read_user_id(token)
