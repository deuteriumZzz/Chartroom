.PHONY: up lint test audit user seed eval eval-agent

up:
	docker compose up --build

# ruff — стиль и ошибки; mypy — типы; lint-imports — границы слоёв (ADR-001).
lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy
	uv run lint-imports

# Интеграционным тестам нужны Postgres (отдельная БД chartroom_test), Qdrant и Redis.
test:
	docker compose up -d --wait db qdrant redis
	uv run pytest --cov

# Известные уязвимости в зафиксированных зависимостях (то же проверяет CI).
audit:
	uv export --frozen --no-dev --no-emit-project | uvx pip-audit --requirement /dev/stdin --no-deps --disable-pip

# make user EMAIL=admin@ship.test ROLE=admin  (пароль спросит интерактивно)
user:
	docker compose exec api python -m chartroom.cli create-user $(EMAIL) --role $(ROLE)

# Загрузить демо-корпус в индексацию и стартовые шаблоны отчётов (нужен GEMINI_API_KEY в .env).
seed:
	docker compose exec api python -m chartroom.cli seed-corpus
	docker compose exec api python -m chartroom.cli seed-templates

# Eval на поднятом стеке (make up && make seed): процесс на хосте ходит в Postgres и Qdrant по
# localhost. EVAL_USER — пользователь, от имени которого задаются вопросы; ARGS=--retrieval-only — без
# генерации (не тратит лимит модели).
eval:
	DATABASE_URL=postgresql+asyncpg://chartroom:chartroom@localhost:5432/chartroom \
	QDRANT_URL=http://localhost:6333 \
	uv run python -m chartroom.cli eval --as $(or $(EVAL_USER),admin@ship.test) $(ARGS)

# Eval агента (FR-23) по eval/agent_golden.yaml. По умолчанию от имени офицера: сценарии с prompt
# injection и чужими отчётами проверяют настоящие права, а не права admin.
eval-agent:
	DATABASE_URL=postgresql+asyncpg://chartroom:chartroom@localhost:5432/chartroom \
	QDRANT_URL=http://localhost:6333 \
	uv run python -m chartroom.cli eval --agent --golden eval/agent_golden.yaml \
	--as $(or $(EVAL_USER),officer@ship.test)
