"""Golden test-vector runner — the accounting correctness gate (AC-11).

Loads every vector under ``engine/vectors/*.json``, replays its postings through
the engine, and asserts the resulting trial balance exactly matches the declared
expectation. A failing vector blocks merge (the CI ``golden-vectors`` job runs
this). New posting paths MUST add a vector.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ledgerline_engine.account import Account, AccountType
from ledgerline_engine.ledger import trial_balance
from ledgerline_engine.money import Money
from ledgerline_engine.posting import Posting, PostingLine
from ledgerline_engine.reports import balance_sheet, profit_and_loss

VECTORS_DIR = Path(__file__).resolve().parents[1] / "vectors"

_TYPE_MAP = {
    "asset": AccountType.ASSET,
    "liability": AccountType.LIABILITY,
    "equity": AccountType.EQUITY,
    "income": AccountType.INCOME,
    "expense": AccountType.EXPENSE,
}


def _load_vectors() -> list[tuple[str, dict[str, Any]]]:
    files = sorted(VECTORS_DIR.glob("*.json"))
    return [(f.name, json.loads(f.read_text(encoding="utf-8"))) for f in files]


VECTORS = _load_vectors()


def test_vectors_present() -> None:
    """The gate must never silently pass with zero vectors."""
    assert VECTORS, "No golden vectors found — the engine gate would be empty"


@pytest.mark.parametrize(("name", "vector"), VECTORS, ids=[n for n, _ in VECTORS])
def test_golden_vector(name: str, vector: dict[str, Any]) -> None:
    base_currency = vector["base_currency"]
    accounts = {
        a["code"]: Account(a["code"], a["name"], _TYPE_MAP[a["type"]])
        for a in vector["accounts"]
    }

    postings = []
    for raw in vector["postings"]:
        lines = []
        for ln in raw["lines"]:
            account = accounts[ln["account"]]
            # If amount currency differs from base, the vector would specify it;
            # default to base currency for both legs.
            amount = Money(ln["amount"], ln.get("currency", base_currency))
            base_amount = Money(ln["base_amount"], base_currency)
            lines.append(
                PostingLine(
                    account=account,
                    amount=amount,
                    base_amount=base_amount,
                    is_debit=ln["debit"],
                )
            )
        postings.append(Posting.of(lines, base_currency=base_currency))

    account_list = list(accounts.values())
    rows = trial_balance(account_list, postings, base_currency=base_currency)
    actual = {
        r.account.code: (r.debit.minor_units, r.credit.minor_units) for r in rows
    }
    expected = {
        e["account"]: (e["debit"], e["credit"]) for e in vector["expected_trial_balance"]
    }
    assert actual == expected, f"Trial balance mismatch in vector {name}"

    # Optional: P&L net profit expectation (minor units).
    if "expected_net_profit" in vector:
        pnl = profit_and_loss(account_list, postings, base_currency=base_currency)
        assert pnl.net_profit is not None
        assert pnl.net_profit.minor_units == vector["expected_net_profit"], (
            f"Net profit mismatch in vector {name}"
        )

    # Optional: Balance Sheet totals expectation (minor units).
    if "expected_balance_sheet" in vector:
        bs = balance_sheet(account_list, postings, base_currency=base_currency)
        exp = vector["expected_balance_sheet"]
        assert bs.total_assets is not None
        assert bs.total_liabilities is not None
        assert bs.total_equity is not None
        assert bs.total_assets.minor_units == exp["assets"], f"Assets mismatch in {name}"
        assert bs.total_liabilities.minor_units == exp["liabilities"], (
            f"Liabilities mismatch in {name}"
        )
        assert bs.total_equity.minor_units == exp["equity"], f"Equity mismatch in {name}"
