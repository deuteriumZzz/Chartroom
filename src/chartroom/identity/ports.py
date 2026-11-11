"""Что сервису identity нужно от внешнего мира. Реализации — в adapters/ и в тестовых фейках."""

from typing import Protocol, Self

from chartroom.identity.domain import Role, User


class UserRepository(Protocol):
    async def get(self, user_id: int) -> User | None: ...

    async def get_by_email(self, email: str) -> User | None: ...

    async def add(self, email: str, password_hash: str, role: Role) -> User:
        """Raises EmailAlreadyRegisteredError, если email занят."""
        ...


class IdentityUnitOfWork(Protocol):
    @property
    def users(self) -> UserRepository: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(self, *exc_info: object) -> None: ...

    async def commit(self) -> None: ...


class PasswordHasher(Protocol):
    async def hash(self, password: str) -> str: ...

    async def verify(self, password: str, password_hash: str | None) -> bool:
        """password_hash=None (нет пользователя): проверка той же длительности, ответ False."""
        ...


class TokenService(Protocol):
    def issue(self, user_id: int) -> str: ...

    def read_user_id(self, token: str) -> int:
        """Raises InvalidTokenError."""
        ...
