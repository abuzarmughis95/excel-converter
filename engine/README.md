# Ledgerline Accounting Engine

The canonical double-entry accounting core. **Pure, deterministic, and
dependency-free** so it runs identically in the FastAPI backend and the Electron
Python sidecar — guaranteeing the numbers are the same online and offline.

## What's here (Phase 2 so far)

| Module | Responsibility |
| ------ | -------------- |
| `money.py` | `Money` — integer minor units, exact arithmetic, named rounding (no floats) |
| `account.py` | `Account`, `AccountType`, normal-balance derivation, control kinds |
| `period.py` | `Period` + lock state machine (open → soft_closed → locked) |
| `posting.py` | `Posting` / `PostingLine` — **unbalanced is unconstructable** |
| `ledger.py` | `trial_balance` — net per-account position, balances to zero |
| `api.py` | Stable public surface (import from here) |

## The golden vectors (the gate)

`vectors/*.json` are canonical scenarios with their expected trial balance.
`tests/test_golden_vectors.py` replays each through the engine and asserts the
result. **A failing vector blocks merge** (CI `engine` job). Every new posting
path must add a vector.

## Local development

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   |   POSIX: source .venv/bin/activate
pip install -e ".[dev]"

ruff check .     # lint
mypy             # strict type checking
pytest           # tests + golden vectors, coverage >= 95%
```

## Principles

- **No floats for money — ever.** Integer minor units; rounding is explicit and
  applied once.
- **Illegal states are unrepresentable.** You cannot hold an unbalanced posting.
- **Determinism.** Same inputs ⇒ byte-identical outputs, on every host.
