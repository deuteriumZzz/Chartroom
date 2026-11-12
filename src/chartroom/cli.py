"""Служебные команды.

create-user — первый admin создаётся здесь: открытой регистрации в API нет.
chunk       — показать, как документ режется на фрагменты (проверка корпуса и настройка нарезки).
seed-corpus — загрузить демо-корпус по манифесту и поставить его в очередь индексации.
eval        — прогнать золотой набор, записать отчёт в eval/results и таблицу метрик в README.
seed-templates — загрузить стартовые шаблоны отчётов (уже существующие пропускаются).
"""

import argparse
import asyncio
import getpass
import json
import os
import pathlib
import sys
import textwrap
from collections.abc import Sequence
from datetime import date
from typing import Any

from chartroom.bootstrap import build_container, build_document_chunker
from chartroom.evaluation.adapters.files import (
    RunInfo,
    current_commit,
    load_golden,
    render_markdown,
    update_readme,
    write_report,
)
from chartroom.evaluation.adapters.qa import QaAnswerProbe, QaRetrievalProbe
from chartroom.evaluation.domain import CaseResult, GoldenCase, summarize
from chartroom.evaluation.service import DEFAULT_K, Evaluator
from chartroom.identity.domain import Role, User
from chartroom.knowledge.domain.models import DocumentUpload, Language
from chartroom.qa.adapters.gemini import ANSWER_PROMPT
from chartroom.shared.config import get_settings
from chartroom.shared.errors import ConflictError, DomainError, ServiceUnavailableError


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
    chunks = build_document_chunker().chunk(path.name, path.read_bytes())
    print(f"{path}: {len(chunks)} chunks")
    for chunk in chunks:
        page = "-" if chunk.page is None else str(chunk.page)
        print(f"#{chunk.index:<3} {chunk.token_count:>4} tok  p.{page:<3} {chunk.section_path}")
        print(f"     {textwrap.shorten(chunk.text, width=110)}")


def _load_corpus(manifest: pathlib.Path) -> list[tuple[str, DocumentUpload]]:
    corpus = []
    for entry in json.loads(manifest.read_text(encoding="utf-8")):
        path = manifest.parent / entry["path"]
        upload = DocumentUpload(
            title=entry["title"],
            language=Language(entry["language"]),
            label=entry["version"],
            issued_on=date.fromisoformat(entry["issued_on"]),
            filename=path.name,
            content=path.read_bytes(),
        )
        corpus.append((entry["path"], upload))
    return corpus


async def _seed_corpus(corpus: list[tuple[str, DocumentUpload]]) -> None:
    container = build_container(get_settings())
    try:
        for name, upload in corpus:
            try:
                version = await container.library.upload(upload)
            except ConflictError:
                print(f"skipped  {name}  (already uploaded)")
            else:
                print(f"queued   {name}  (version {version.label}, id={version.id})")
    finally:
        await container.aclose()


async def _evaluate(cases: list[GoldenCase], as_email: str, with_answers: bool) -> list[CaseResult]:
    container = build_container(get_settings())
    try:
        # Вопросы eval задаёт существующий пользователь: журнал честно показывает, кто их задавал.
        user = await container.identity.user_by_email(as_email)
        evaluator = Evaluator(
            QaRetrievalProbe(container.passages), QaAnswerProbe(container.questions, user.id)
        )
        return await evaluator.run(cases, with_answers)
    finally:
        await container.aclose()


def _run_eval(args: argparse.Namespace) -> None:
    with_answers = not args.retrieval_only
    results = asyncio.run(_evaluate(load_golden(args.golden), args.as_email, with_answers))
    settings = get_settings()
    run = RunInfo(
        date=date.today(),
        commit=current_commit(pathlib.Path.cwd()),
        generation_models=tuple(settings.generation_models),
        prompt_version=ANSWER_PROMPT,
        embedding_model=settings.embedding_model,
        refusal_threshold=settings.refusal_min_similarity,
        with_answers=with_answers,
    )
    metrics = summarize(results, DEFAULT_K)
    report = write_report(args.results_dir, run, metrics, results)
    markdown = render_markdown(run, metrics)
    update_readme(args.readme, markdown)
    print(f"{markdown}\n\nreport: {report}")


def _load_templates(directory: pathlib.Path) -> list[dict[str, Any]]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(directory.glob("*.json"))]


async def _seed_templates(templates: list[dict[str, Any]]) -> None:
    container = build_container(get_settings())
    try:
        existing = {t.name for t in await container.reports.templates()}
        for spec in templates:
            if spec["name"] in existing:
                print(f"skipped  {spec['name']}  (already exists)")
                continue
            template = await container.reports.create_template(
                spec["name"], spec["title"], spec["schema"]
            )
            print(f"created  {template.name}  (version {template.version})")
    finally:
        await container.aclose()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="chartroom")
    commands = parser.add_subparsers(dest="command", required=True)
    create_user = commands.add_parser("create-user", help="создать пользователя")
    create_user.add_argument("email")
    create_user.add_argument("--role", type=Role, choices=list(Role), required=True)
    chunk = commands.add_parser("chunk", help="показать нарезку документа на фрагменты")
    chunk.add_argument("path", type=pathlib.Path)
    seed = commands.add_parser("seed-corpus", help="загрузить демо-корпус в очередь индексации")
    seed.add_argument(
        "--manifest", type=pathlib.Path, default=pathlib.Path("data/corpus/manifest.json")
    )
    templates = commands.add_parser("seed-templates", help="загрузить стартовые шаблоны отчётов")
    templates.add_argument("--dir", type=pathlib.Path, default=pathlib.Path("data/templates"))
    evaluate = commands.add_parser("eval", help="прогнать золотой набор и записать метрики")
    evaluate.add_argument("--as", dest="as_email", required=True, help="email пользователя")
    evaluate.add_argument("--golden", type=pathlib.Path, default=pathlib.Path("eval/golden.yaml"))
    evaluate.add_argument("--results-dir", type=pathlib.Path, default=pathlib.Path("eval/results"))
    evaluate.add_argument("--readme", type=pathlib.Path, default=pathlib.Path("README.md"))
    evaluate.add_argument(
        "--retrieval-only", action="store_true", help="только поиск, без вызова модели генерации"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    try:
        if args.command == "create-user":
            _create_user(args.email, args.role)
        elif args.command == "chunk":
            _show_chunks(args.path)
        elif args.command == "seed-corpus":
            asyncio.run(_seed_corpus(_load_corpus(args.manifest)))
        elif args.command == "seed-templates":
            asyncio.run(_seed_templates(_load_templates(args.dir)))
        else:
            _run_eval(args)
    except (DomainError, ServiceUnavailableError, OSError, ValueError) as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()
