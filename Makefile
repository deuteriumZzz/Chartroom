.PHONY: up lint test user seed eval

up:
	docker compose up --build

# ruff — стиль и ошибки; mypy — типы; lint-imports — границы слоёв (ADR-001).
lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy
	uv run lint-imports

# Интеграционным тестам нужны Postgres (отдельная БД chartroom_test) и Qdrant.
test:
	docker compose up -d --wait db qdrant
	uv run pytest --cov

# make user EMAIL=admin@ship.test ROLE=admin  (пароль спросит интерактивно)
user:
	docker compose exec api python -m chartroom.cli create-user $(EMAIL) --role $(ROLE)

# Загрузить демо-корпус и поставить его в очередь индексации (нужен GEMINI_API_KEY в .env).
seed:
	docker compose exec api python -m chartroom.cli seed-corpus

# Eval на поднятом стеке (make up && make seed): процесс на хосте ходит в Postgres и Qdrant по
# localhost. EVAL_USER — пользователь, от имени которого задаются вопросы; ARGS=--retrieval-only — без
# генерации (не тратит лимит модели).
eval:
	DATABASE_URL=postgresql+asyncpg://chartroom:chartroom@localhost:5432/chartroom \
	QDRANT_URL=http://localhost:6333 \
	uv run python -m chartroom.cli eval --as $(or $(EVAL_USER),admin@ship.test) $(ARGS)
