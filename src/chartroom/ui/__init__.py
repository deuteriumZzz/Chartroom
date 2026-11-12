"""Минимальный интерфейс без сборки: статические файлы, которые ходят в тот же API."""

import pathlib

from fastapi import APIRouter
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

STATIC = pathlib.Path(__file__).parent / "static"
router = APIRouter(include_in_schema=False)
files = StaticFiles(directory=STATIC)


@router.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")
