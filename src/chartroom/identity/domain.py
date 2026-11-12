"""Пользователи и роли. Чистые правила — без фреймворков и I/O."""

import re
from dataclasses import dataclass
from enum import StrEnum

from chartroom.shared.errors import (
    AuthenticationError,
    ConflictError,
    InvalidInputError,
    NotFoundError,
    PermissionDeniedError,
)

MIN_PASSWORD_LENGTH = 8
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MAX_EMAIL_LENGTH = 320  # RFC 5321


class Role(StrEnum):
    OFFICER = "officer"
    CAPTAIN = "captain"
    ADMIN = "admin"

    def is_at_least(self, required: "Role") -> bool:
        return _RANK[self] >= _RANK[required]


# «officer+» в ТЗ: старшая роль включает права младших.
_RANK = {Role.OFFICER: 1, Role.CAPTAIN: 2, Role.ADMIN: 3}


class InvalidCredentialsError(AuthenticationError):
    # Не уточняем, что неверно: email или пароль — иначе можно перебрать зарегистрированные email.
    message = "Incorrect email or password"


class InvalidTokenError(AuthenticationError):
    message = "Invalid or expired token"


class InsufficientRoleError(PermissionDeniedError):
    message = "Insufficient role"


class UserNotFoundError(NotFoundError):
    message = "User not found"


class EmailAlreadyRegisteredError(ConflictError):
    message = "Email is already registered"


class InvalidEmailError(InvalidInputError):
    message = "Invalid email"


class WeakPasswordError(InvalidInputError):
    message = f"Password must be at least {MIN_PASSWORD_LENGTH} characters"


@dataclass(frozen=True, slots=True)
class User:
    id: int
    email: str
    password_hash: str
    role: Role

    def ensure_role(self, minimum: Role) -> None:
        if not self.role.is_at_least(minimum):
            raise InsufficientRoleError


def normalize_email(raw: str) -> str:
    return raw.strip().lower()


def ensure_valid_email(email: str) -> None:
    if len(email) > _MAX_EMAIL_LENGTH or not _EMAIL.fullmatch(email):
        raise InvalidEmailError


def ensure_strong_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPasswordError
