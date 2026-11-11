import asyncio

from pwdlib import PasswordHash


class Argon2PasswordHasher:
    """argon2id через pwdlib. Хеширование нагружает CPU, поэтому уходит в поток из event loop."""

    def __init__(self) -> None:
        self._hasher = PasswordHash.recommended()
        self._dummy_hash = self._hasher.hash("timing-equalizer")

    async def hash(self, password: str) -> str:
        return await asyncio.to_thread(self._hasher.hash, password)

    async def verify(self, password: str, password_hash: str | None) -> bool:
        # Для несуществующего пользователя проверяем фиктивный хеш: ответ занимает столько же
        # времени, и по таймингу нельзя узнать, зарегистрирован ли email.
        target = password_hash or self._dummy_hash
        ok = await asyncio.to_thread(self._hasher.verify, password, target)
        return ok and password_hash is not None
