.PHONY: up lint test user seed

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
