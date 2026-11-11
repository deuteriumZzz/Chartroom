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
