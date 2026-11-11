from collections.abc import Callable

from chartroom.identity.domain import (
    InvalidCredentialsError,
    InvalidTokenError,
    Role,
    User,
    ensure_strong_password,
    ensure_valid_email,
    normalize_email,
)
from chartroom.identity.ports import IdentityUnitOfWork, PasswordHasher, TokenService


class IdentityService:
    """Сценарии модуля: вход, проверка токена, регистрация. Знает только порты."""

    def __init__(
        self,
        uow_factory: Callable[[], IdentityUnitOfWork],
        hasher: PasswordHasher,
        tokens: TokenService,
    ) -> None:
        # Фабрика, а не готовый UoW: сервис живёт всё время работы приложения,
        # а транзакция у каждого вызова своя.
        self._uow_factory = uow_factory
        self._hasher = hasher
        self._tokens = tokens

    async def login(self, email: str, password: str) -> str:
        """Возвращает access-токен."""
        async with self._uow_factory() as uow:
            user = await uow.users.get_by_email(normalize_email(email))
        password_ok = await self._hasher.verify(password, user.password_hash if user else None)
        if user is None or not password_ok:
            raise InvalidCredentialsError
        return self._tokens.issue(user.id)

    async def authenticate(self, token: str) -> User:
        user_id = self._tokens.read_user_id(token)
        async with self._uow_factory() as uow:
            user = await uow.users.get(user_id)
        if user is None:  # пользователь удалён после выдачи токена
            raise InvalidTokenError
        return user

    async def register(self, email: str, password: str, role: Role) -> User:
        email = normalize_email(email)
        ensure_valid_email(email)
        ensure_strong_password(password)
        password_hash = await self._hasher.hash(password)
        async with self._uow_factory() as uow:
            user = await uow.users.add(email, password_hash, role)
            await uow.commit()
        return user
