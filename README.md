# Chartroom

Ассистент по судовым процедурам (SMS/ISM) и отчётам. Отвечает только по загруженным документам, со ссылкой на раздел и страницу. Если источника нет — честно отказывает, а не угадывает.

> **Демо-проект.** Корпус процедур синтетический, реальных данных судоходных компаний нет.
> **Статус:** в разработке, день 3 из 16 — корпус процедур, разбор документов и нарезка. Метрики качества появятся здесь после первого `make eval`, до этого чисел не будет.

## Запуск

```bash
make up                                     # API и Swagger: http://localhost:8088/docs
make user EMAIL=admin@ship.test ROLE=admin  # первый пользователь (пароль спросит)
```

Демо-настройки берутся из `.env.example`. Для своих значений: `cp .env.example .env`.

## Разработка

```bash
make lint   # ruff, mypy --strict, границы слоёв (import-linter)
make test   # unit и интеграционные тесты на Postgres, покрытие ≥ 95%
uv run python -m chartroom.cli chunk data/corpus/ru/fire-emergency.md  # как документ режется на фрагменты
```

## Документация

[Архитектура](docs/architecture.md) · [ADR](docs/adr/) · [Журнал ошибок ИИ](docs/ai-log.md) · [ТЗ](PROJECT_SPEC.md)
