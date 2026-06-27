# Ledgerline

Offline-first UK accounting & compliance platform. Desktop-first (Electron) with
cloud sync, designed to compete with VT Software and QuickBooks.

> **Status:** Phase 1 (Foundation). This repository currently contains the
> monorepo scaffold, a bootable backend, a secure Electron shell with a React
> renderer, and shared primitives. Accounting engine, sync, and business modules
> land in later phases per the implementation plan.

## Repository layout

```
ledgerline/
├── apps/
│   ├── backend/        # Python FastAPI service (system of record, sync gateway)
│   └── desktop/        # Electron app + React/TypeScript renderer
├── packages/
│   └── shared-types/   # Shared TS types & primitives (Money, IDs, event envelope)
├── engine/             # Python accounting core (Phase 2 — not yet present)
├── docker-compose.yml  # Local Postgres + Redis
└── .github/workflows/  # CI (lint, typecheck, test, build, golden-vector gate)
```

## Prerequisites

- Node.js 20.x and pnpm 9.x (`corepack enable` or `npm i -g pnpm@9.12.0`)
- Python 3.12
- Docker (optional, for Postgres/Redis)

## Getting started

```bash
# JavaScript / TypeScript workspace
pnpm install
pnpm build
pnpm test

# Backend
cd apps/backend
python -m venv .venv && . .venv/Scripts/activate   # POSIX: source .venv/bin/activate
pip install -e ".[dev]"
pytest

# Backing services
docker compose up -d postgres redis
```

## Quality gates (run in CI on every PR)

| Area    | Commands                                                  |
| ------- | --------------------------------------------------------- |
| TS/JS   | `pnpm lint`, `pnpm typecheck`, `pnpm test`, `pnpm build`  |
| Python  | `ruff check .`, `mypy`, `pytest` (coverage ≥ 90%)         |
| Gate    | Accounting golden vectors (wired; implemented in Phase 2) |
| Secrets | gitleaks secret scan                                      |

## Engineering principles

- **No floats for money.** Integer minor units everywhere; rounding is explicit.
- **One accounting engine** in Python, run on both server and desktop.
- **Event-sourced sync**; audit trail and data integrity are non-negotiable.
- **TypeScript strict mode** and **Python type hints (mypy strict)** throughout.
- Small, focused, tested commits — one ticket at a time.
