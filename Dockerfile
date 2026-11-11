FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
WORKDIR /app

# Сначала только зависимости: слой кешируется, пока не меняется uv.lock.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
RUN uv sync --frozen --no-dev

# Приложению не нужны права root: при компрометации процесса это ограничивает ущерб.
RUN useradd --uid 10001 --no-create-home app
USER app

ENV PATH="/app/.venv/bin:$PATH"
CMD ["sh", "-c", "alembic upgrade head && uvicorn --factory chartroom.main:create_app --host 0.0.0.0 --port 8000"]
