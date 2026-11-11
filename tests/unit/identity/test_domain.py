import pytest

from chartroom.identity.domain import (
    InsufficientRoleError,
    InvalidEmailError,
    Role,
    User,
    WeakPasswordError,
    ensure_strong_password,
    ensure_valid_email,
    normalize_email,
)


@pytest.mark.parametrize(
    ("role", "required", "allowed"),
    [
        (Role.OFFICER, Role.OFFICER, True),
        (Role.OFFICER, Role.CAPTAIN, False),
        (Role.OFFICER, Role.ADMIN, False),
        (Role.CAPTAIN, Role.OFFICER, True),
        (Role.CAPTAIN, Role.ADMIN, False),
        (Role.ADMIN, Role.OFFICER, True),
        (Role.ADMIN, Role.CAPTAIN, True),
    ],
)
def test_role_hierarchy(role: Role, required: Role, allowed: bool) -> None:
    assert role.is_at_least(required) is allowed


def test_ensure_role_raises_for_junior_role() -> None:
    officer = User(id=1, email="o@ship.test", password_hash="h", role=Role.OFFICER)
    officer.ensure_role(Role.OFFICER)
    with pytest.raises(InsufficientRoleError):
        officer.ensure_role(Role.ADMIN)


def test_normalize_email() -> None:
    assert normalize_email("  Officer@Ship.TEST ") == "officer@ship.test"


@pytest.mark.parametrize(
    "email", ["no-at-sign", "a@b", "a b@ship.test", "@ship.test", "a" * 316 + "@x.io"]
)
def test_invalid_email_rejected(email: str) -> None:
    with pytest.raises(InvalidEmailError):
        ensure_valid_email(email)


def test_valid_email_accepted() -> None:
    ensure_valid_email("second.officer@ship.test")


def test_password_length_policy() -> None:
    ensure_strong_password("8-chars!")
    with pytest.raises(WeakPasswordError):
        ensure_strong_password("7-chars")
