"""Служебные команды.

create-user — первый admin создаётся здесь: открытой регистрации в API нет.
chunk       — показать, как документ режется на фрагменты (проверка корпуса и настройка нарезки).
"""

import argparse
import asyncio
import getpass
import os
import pathlib
import sys
import textwrap
from collections.abc import Sequence

from chartroom.bootstrap import build_container, build_knowledge_service
from chartroom.identity.domain import Role, User
from chartroom.shared.config import get_settings
from chartroom.shared.errors import DomainError


async def _register(email: str, password: str, role: Role) -> User:
    container = build_container(get_settings())
    try:
        return await container.identity.register(email, password, role)
    finally:
        await container.aclose()


def _create_user(email: str, role: Role) -> None:
    # Пароль не принимаем аргументом: он остался бы в истории shell и в выводе `ps`.
    password = os.environ.get("CHARTROOM_PASSWORD") or getpass.getpass("Password: ")
    user = asyncio.run(_register(email, password, role))
    print(f"created user id={user.id} email={user.email} role={user.role}")


def _show_chunks(path: pathlib.Path) -> None:
    chunks = build_knowledge_service().chunk(path.name, path.read_bytes())
    print(f"{path}: {len(chunks)} chunks")
    for chunk in chunks:
        page = "-" if chunk.page is None else str(chunk.page)
        print(f"#{chunk.index:<3} {chunk.token_count:>4} tok  p.{page:<3} {chunk.section_path}")
        print(f"     {textwrap.shorten(chunk.text, width=110)}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="chartroom")
    commands = parser.add_subparsers(dest="command", required=True)
    create_user = commands.add_parser("create-user", help="создать пользователя")
    create_user.add_argument("email")
    create_user.add_argument("--role", type=Role, choices=list(Role), required=True)
    chunk = commands.add_parser("chunk", help="показать нарезку документа на фрагменты")
    chunk.add_argument("path", type=pathlib.Path)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    try:
        if args.command == "create-user":
            _create_user(args.email, args.role)
        else:
            _show_chunks(args.path)
    except (DomainError, OSError) as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()
