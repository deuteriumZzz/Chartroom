"""In-memory реализации портов для unit-тестов. Совпадение поведения с SQL-адаптерами
проверяют контрактные тесты в tests/integration/identity/test_unit_of_work_contract.py."""

from typing import Self

from chartroom.identity.domain import EmailAlreadyRegisteredError, Role, User


class InMemoryUserRepository:
    def __init__(self, users: dict[int, User]) -> None:
        self._users = users

    async def get(self, user_id: int) -> User | None:
        return self._users.get(user_id)

    async def get_by_email(self, email: str) -> User | None:
        return next((u for u in self._users.values() if u.email == email), None)

    async def add(self, email: str, password_hash: str, role: Role) -> User:
        if await self.get_by_email(email):
            raise EmailAlreadyRegisteredError
        user = User(
            id=max(self._users, default=0) + 1, email=email, password_hash=password_hash, role=role
        )
        self._users[user.id] = user
        return user


class InMemoryIdentityUnitOfWork:
    """Та же транзакционность, что у SQL: изменения видны снаружи только после commit()."""

    users: InMemoryUserRepository

    def __init__(self, store: dict[int, User]) -> None:
        self._store = store

    async def __aenter__(self) -> Self:
        self._pending = dict(self._store)
        self.users = InMemoryUserRepository(self._pending)
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def commit(self) -> None:
        self._store.update(self._pending)


class FakePasswordHasher:
    """Без argon2: unit-тесты сервиса проверяют сценарии, а не криптографию."""

    async def hash(self, password: str) -> str:
        return f"hashed:{password}"

    async def verify(self, password: str, password_hash: str | None) -> bool:
        return password_hash == f"hashed:{password}"
