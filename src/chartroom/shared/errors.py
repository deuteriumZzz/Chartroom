"""Ошибки предметной области. Транспорт (HTTP, CLI) сам решает, как их показать."""

from typing import ClassVar


class DomainError(Exception):
    """Ожидаемая бизнес-ошибка: её текст безопасно показывать клиенту."""

    message: ClassVar[str] = "Request cannot be processed"

    def __str__(self) -> str:
        return self.message


class AuthenticationError(DomainError):
    pass


class PermissionDeniedError(DomainError):
    pass


class ConflictError(DomainError):
    pass


class InvalidInputError(DomainError):
    pass


class NotFoundError(DomainError):
    pass


class ServiceUnavailableError(Exception):
    """Внешний сервис (провайдер эмбеддингов, векторное хранилище, очередь) недоступен.

    Не бизнес-ошибка и не наследник DomainError: обычно временная, операцию можно повторить.
    Текст задаёт адаптер и показывает клиенту — в нём нет деталей инфраструктуры.
    """
