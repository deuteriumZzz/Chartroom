.PHONY: up lint test user

up:
	docker compose up --build

# ruff — стиль и ошибки; mypy — типы.
lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy

# Интеграционным тестам нужен Postgres; они работают в отдельной БД chartroom_test.
test:
	docker compose up -d --wait db
	uv run pytest

# make user EMAIL=admin@ship.test ROLE=admin  (пароль спросит интерактивно)
user:
	docker compose exec api python -m chartroom.cli create-user $(EMAIL) --role $(ROLE)
