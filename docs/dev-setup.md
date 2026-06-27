# Development Environment Setup

## Prerequisites

- **Node.js 20.x** (see `.nvmrc`)
- **pnpm 9.12** — `npm install -g pnpm@9.12.0` (or `corepack enable` where permitted)
- **Python 3.12**
- **Docker + Docker Compose** (optional, for backing services)

## First-time setup

```bash
# 1. JS/TS workspace
pnpm install

# 2. Backend virtualenv
cd apps/backend
python -m venv .venv
# Windows (PowerShell): .venv\Scripts\Activate.ps1
# POSIX:                source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
cd ../..

# 3. Backing services (optional)
docker compose up -d postgres redis
```

> **Ports:** the Docker Postgres maps to host **5433** by default (5432 is often
> taken by a native PostgreSQL install) and Redis to **6380**. Override with
> `LEDGERLINE_PG_PORT` / `LEDGERLINE_REDIS_PORT`. The backend's default
> `LEDGERLINE_DATABASE_URL` already points at 5433.
>
> To run the PostgreSQL integration tests locally, set
> `LEDGERLINE_TEST_PG_URL=postgresql+psycopg://ledgerline:ledgerline_dev_only@localhost:5433/ledgerline`
> before `pytest` (they skip when unset).

## Running things

| Target           | Command                                                          |
| ---------------- | ---------------------------------------------------------------- |
| Backend (dev)    | `cd apps/backend && uvicorn ledgerline_backend.app:app --reload` |
| Desktop renderer | `pnpm --filter @ledgerline/desktop dev`                          |
| Desktop (full)   | `pnpm --filter @ledgerline/desktop build` then launch Electron   |

## Quality gates

```bash
# TypeScript / JavaScript (from repo root)
pnpm lint
pnpm typecheck
pnpm test
pnpm build

# Python (from apps/backend, venv active)
ruff check .
mypy
pytest
```

## Notes

- The Electron **main and preload** processes compile to **CommonJS** (`dist/`
  carries a `{"type":"commonjs"}` marker); the **renderer** is built as ESM by
  Vite. Mixing is intentional and matches the mainstream Electron+TS setup.
- **Gotcha:** if `ELECTRON_RUN_AS_NODE=1` is set in your shell, Electron runs as
  plain Node and `require('electron')` returns a path string instead of the API
  (the app will appear to "not start"). Unset it before launching:
  `pnpm --filter @ledgerline/desktop smoke` (the script clears it on CI).
- Money is always handled as integer minor units — never floats. See
  `packages/shared-types/src/money.ts`.
- Legacy design notes from earlier exploration are preserved under
  `_preserved_legacy_docs/` and are superseded by the formal architecture.
