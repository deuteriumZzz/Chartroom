.PHONY: up lint test user

up:
	docker compose up --build

# ruff — стиль и ошибки; mypy — типы; lint-imports — границы слоёв (ADR-001).
lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy
	uv run lint-imports

# Интеграционным тестам нужен Postgres; они работают в отдельной БД chartroom_test.
test:
	docker compose up -d --wait db
	uv run pytest --cov

# make user EMAIL=admin@ship.test ROLE=admin  (пароль спросит интерактивно)
user:
	docker compose exec api python -m chartroom.cli create-user $(EMAIL) --role $(ROLE)
