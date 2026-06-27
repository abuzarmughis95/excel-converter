"""Tests for bank-statement extraction parsing (no real OpenAI calls)."""

from __future__ import annotations

from typing import Any

from ledgerline_backend.services.statement_extraction import (
    ModelClient,
    StatementExtractionError,
    _loads_json,
    _to_minor,
    extract_statement,
    parse_extraction,
)

SAMPLE: dict[str, Any] = {
    "currency": "GBP",
    "summary": {
        "account_name": "ACME LTD",
        "account_number": "12345678",
        "sort_code": "12-34-56",
        "period_start": "01/06/2026",
        "period_end": "30/06/2026",
        "opening_balance": 1000.00,
        "closing_balance": 1150.00,
    },
    "lines": [
        {"date": "02/06/2026", "description": "CARD PAYMENT", "money_out": 50.00, "money_in": None, "balance": 950.00},
        {"date": "10/06/2026", "description": "SALES RECEIPT", "money_out": None, "money_in": 200.00, "balance": 1150.00},
    ],
}


def test_to_minor_parses_money() -> None:
    assert _to_minor("1,234.56") == 123456
    assert _to_minor("£50.00") == 5000
    assert _to_minor(1000.0) == 100000
    assert _to_minor(None) is None
    assert _to_minor("") is None
    assert _to_minor("not money") is None


def test_parse_extraction_summary_and_lines() -> None:
    result = parse_extraction(SAMPLE)
    assert result.summary.account_number == "12345678"
    assert result.summary.opening_balance_minor == 100000
    assert result.summary.closing_balance_minor == 115000
    # Dates normalized to ISO.
    assert result.summary.period_start == "2026-06-01"
    assert len(result.lines) == 2
    assert result.lines[0].money_out_minor == 5000
    assert result.lines[1].money_in_minor == 20000


def test_reconciliation_true_when_balances_match() -> None:
    # opening 1000 + (200 in - 50 out) = 1150 = closing.
    assert parse_extraction(SAMPLE).reconciled is True


def test_reconciliation_false_when_mismatch() -> None:
    bad = {**SAMPLE, "summary": {**SAMPLE["summary"], "closing_balance": 9999.00}}
    assert parse_extraction(bad).reconciled is False


def test_reconciliation_false_when_balances_missing() -> None:
    no_balances = {
        "summary": {"opening_balance": None, "closing_balance": None},
        "lines": SAMPLE["lines"],
    }
    assert parse_extraction(no_balances).reconciled is False


def test_parse_handles_empty_payload() -> None:
    result = parse_extraction({})
    assert result.lines == []
    assert result.summary.account_number is None


def test_loads_json_strips_markdown_fence() -> None:
    fenced = '```json\n{"currency": "GBP", "lines": []}\n```'
    assert _loads_json(fenced) == {"currency": "GBP", "lines": []}


def test_loads_json_rejects_non_json() -> None:
    try:
        _loads_json("I could not read the document")
    except StatementExtractionError:
        return
    raise AssertionError("expected StatementExtractionError")


class _FakeClient:
    """A ModelClient returning a canned payload (no network)."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.calls = 0

    def extract(self, *, pdf_bytes: bytes, model: str) -> dict[str, Any]:
        self.calls += 1
        return self._payload


def test_extract_statement_end_to_end_with_fake_client() -> None:
    client: ModelClient = _FakeClient(SAMPLE)
    result = extract_statement(pdf_bytes=b"%PDF-1.4 fake", model="test-model", client=client)
    assert result.reconciled is True
    assert len(result.lines) == 2
