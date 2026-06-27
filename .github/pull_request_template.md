<!-- Ledgerline PR checklist. Commercial accounting software — these are not optional. -->

## Summary

<!-- What does this PR do, and which ticket (e.g. F-01, AC-03) does it implement? -->

## Checklist

- [ ] Implements exactly one ticket; scope is small and focused.
- [ ] Tests added/updated and passing (`pnpm test`, `pytest`).
- [ ] Lint + typecheck pass (`pnpm lint && pnpm typecheck`, `ruff check . && mypy`).
- [ ] No secrets, credentials, or PII committed or logged.
- [ ] If a new posting/accounting path was added: **golden vectors added** (AC-11).
- [ ] If a financial mutation was added: **audit trail entry written and tested**.
- [ ] If sync-affecting: idempotency and conflict behaviour considered/tested.
- [ ] Security/compliance acceptance criteria for the ticket are met.

## Remaining risks

<!-- Anything reviewers should know that is deferred or unverified. -->
