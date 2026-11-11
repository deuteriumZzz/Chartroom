"""Служебные команды. Первый admin создаётся здесь: открытой регистрации в API нет."""

import argparse
import asyncio
import getpass
import os
import sys
from collections.abc import Sequence

from chartroom.bootstrap import build_container
from chartroom.identity.domain import Role, User
from chartroom.shared.config import get_settings
from chartroom.shared.errors import DomainError


async def _register(email: str, password: str, role: Role) -> User:
    container = build_container(get_settings())
    try:
        return await container.identity.register(email, password, role)
    finally:
        await container.aclose()


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="chartroom")
    commands = parser.add_subparsers(dest="command", required=True)
    create_user = commands.add_parser("create-user")
    create_user.add_argument("email")
    create_user.add_argument("--role", type=Role, choices=list(Role), required=True)
    args = parser.parse_args(argv)

    # Пароль не принимаем аргументом: он остался бы в истории shell и в выводе `ps`.
    password = os.environ.get("CHARTROOM_PASSWORD") or getpass.getpass("Password: ")
    try:
        user = asyncio.run(_register(args.email, password, args.role))
    except DomainError as e:
        sys.exit(f"error: {e}")
    print(f"created user id={user.id} email={user.email} role={user.role}")


if __name__ == "__main__":
    main()
