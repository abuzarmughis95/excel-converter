# Golden Test Vectors

Canonical accounting scenarios with their expected outputs. These are the
**contract** for the engine: each vector declares a set of accounts and postings
and the trial balance they must produce. The suite is a **required CI gate**
(`golden-vectors` job) — a failing vector blocks merge.

## Rules

- Every new posting path (transaction type, VAT treatment, FX case) MUST add a
  vector before it is considered done.
- Vectors are authored/reviewed by the domain expert.
- Amounts are integer **minor units** (pence). Never floats.

## Format

Each `*.json` file is one vector:

```json
{
  "name": "human-readable scenario name",
  "base_currency": "GBP",
  "accounts": [{"code": "1200", "name": "Bank", "type": "asset"}, ...],
  "postings": [
    {"lines": [
      {"account": "1200", "amount": 12000, "base_amount": 12000, "debit": true},
      {"account": "4000", "amount": 12000, "base_amount": 12000, "debit": false}
    ]}
  ],
  "expected_trial_balance": [
    {"account": "1200", "debit": 12000, "credit": 0},
    {"account": "4000", "debit": 0, "credit": 12000}
  ]
}
```
