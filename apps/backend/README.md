# Ledgerline Backend

FastAPI service: system of record, sync gateway, and compliance integrations.

## Local development

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   |   POSIX: source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env

uvicorn ledgerline_backend.app:app --reload
```

- Liveness: `GET http://localhost:8000/v1/health`
- Version:  `GET http://localhost:8000/v1/version`
- Docs (non-prod): `http://localhost:8000/docs`

## Database & migrations

```bash
# Apply migrations (uses LEDGERLINE_DATABASE_URL, defaults to local Postgres)
alembic upgrade head

# Roll back one revision / to empty
alembic downgrade -1
alembic downgrade base

# Autogenerate a new migration after changing models
alembic revision --autogenerate -m "describe change"
```

Models live in `src/ledgerline_backend/models/`; the portable `GUID` type and
audit/sync mixins are in `src/ledgerline_backend/db/`. The same models back both
PostgreSQL (server) and SQLite (local/tests).

## Quality gates

```bash
ruff check .          # lint
mypy                  # strict type checking
pytest                # tests + coverage (fails under 90%)
```

## Layout

```
src/ledgerline_backend/
  app.py        # application factory
  config.py     # env-driven, validated settings
  logging.py    # structlog configuration
  api/          # FastAPI routers
tests/          # pytest suite
```
