from typing import Self

from sqlalchemy import Enum, String, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from chartroom.identity.domain import EmailAlreadyRegisteredError, Role, User
from chartroom.shared.database import Base, SqlAlchemyUnitOfWork


class UserRecord(Base):
    """ORM-запись. Наружу не выходит: репозиторий отдаёт доменный User."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(
        Enum(
            Role,
            name="user_role",
            native_enum=False,
            create_constraint=True,
            length=16,
            values_callable=lambda roles: [r.value for r in roles],
        )
    )

    def to_domain(self) -> User:
        return User(id=self.id, email=self.email, password_hash=self.password_hash, role=self.role)


class SqlUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: int) -> User | None:
        record = await self._session.get(UserRecord, user_id)
        return record.to_domain() if record else None

    async def get_by_email(self, email: str) -> User | None:
        record = await self._session.scalar(select(UserRecord).where(UserRecord.email == email))
        return record.to_domain() if record else None

    async def add(self, email: str, password_hash: str, role: Role) -> User:
        record = UserRecord(email=email, password_hash=password_hash, role=role)
        self._session.add(record)
        try:
            await self._session.flush()
        except IntegrityError as e:
            # Уникальность проверяет БД, а не SELECT перед INSERT: так нет гонки двух регистраций.
            # Роль ограничена enum-ом, поэтому единственное нарушимое ограничение — email.
            raise EmailAlreadyRegisteredError from e
        return record.to_domain()


class SqlIdentityUnitOfWork(SqlAlchemyUnitOfWork):
    users: SqlUserRepository

    async def __aenter__(self) -> Self:
        await super().__aenter__()
        self.users = SqlUserRepository(self.session)
        return self
