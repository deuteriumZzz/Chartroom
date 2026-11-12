# Архитектура

Модульный монолит: модули по предметным областям, внутри каждого — порты и адаптеры. Обоснование — [ADR-001](adr/001-modular-monolith.md).

## Слои модуля

```mermaid
flowchart LR
  HTTP["api.py<br/>FastAPI-роутер"] --> S["service.py<br/>сценарии"]
  CLI["cli.py"] --> S
  S --> P["ports.py<br/>Protocol-интерфейсы"]
  S --> D["domain.py<br/>сущности и правила"]
  A["adapters/<br/>SQL, argon2, JWT, Gemini, Qdrant"] -. реализует .-> P
  A --> X[("Postgres · Qdrant · LLM")]
  B["bootstrap.py<br/>точка сборки"] --> A
  B --> S
```

| Слой | Знает | Не знает |
|---|---|---|
| `domain.py` | только себя и `shared.errors` | фреймворки, БД, I/O |
| `ports.py` | домен | реализации |
| `service.py` | порты, домен | FastAPI, SQLAlchemy, внешние SDK |
| `api.py` | сервис, домен | хранилище и адаптеры |
| `adapters/` | порты, домен, свою библиотеку | HTTP |

Правила закреплены контрактами import-linter (`[tool.importlinter]` в `pyproject.toml`) и проверяются в `make lint` и CI.

## Модули

| Модуль | Отвечает за | ТЗ | Статус |
|---|---|---|---|
| `identity` | пользователи, роли, вход | §2 | готов |
| `knowledge` | документы, версии, разбор, нарезка, индексация, гибридный поиск | FR-1, 2, 8 | готов (ADR-004…006) |
| `qa` | вопросы: поиск фрагментов, отказ, генерация, проверка цитат, журнал, отзывы | FR-3…7 | готов (ADR-006…008) |
| `evaluation` | золотые наборы, метрики, отчёты | FR-14, 15, 23 | готов: `make eval`, `make eval-agent` (ADR-009) |
| `reports` | шаблоны, извлечение, проверка, статусы отчётов | FR-9…13 | готов (ADR-011) |
| `agent` | вызов функций (Gemini function calling), только чтение, права пользователя, аудит | FR-16…22 | готов (ADR-012) |

`shared/` — общее ядро без бизнес-логики: конфиг, базовые ошибки, база ORM и Unit of Work.

Модули связаны только через края: HTTP-слои проверяют права через `identity.api`, а `qa` ищет фрагменты через свой порт и адаптер к `knowledge` (ADR-006). Ядра модулей друг друга не импортируют — это проверяет контракт независимости.

Точки сборки две: `main.py` (API) и `worker.py` (Celery-worker индексации). Обе берут зависимости из `bootstrap.py`.

## Ошибки
Домен бросает наследников `DomainError`: `AuthenticationError` → 401, `PermissionDeniedError` → 403, `NotFoundError` → 404, `ConflictError` → 409, `InvalidInputError` → 422. Недоступность внешнего сервиса — `ServiceUnavailableError` → 503 с `Retry-After`: это не бизнес-ошибка, и её можно повторить. Перевод в HTTP-статусы сделан в одном месте (`main.py`), поэтому новый модуль не трогает обработчики.

## Как добавить модуль
1. `chartroom/<module>/` с `domain.py`, `ports.py`, `service.py`, `api.py`, `adapters/`.
2. Добавить модуль в `containers`, `source_modules` и `modules` (контракт независимости) import-linter.
3. Собрать сервис в `bootstrap.py`, подключить роутер в `main.py`.
4. Тесты: домен и сервис — на фейках; адаптеры — контрактный набор на фейке и реальной инфраструктуре.
