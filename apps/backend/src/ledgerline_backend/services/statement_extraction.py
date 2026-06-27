"""Bank statement extraction via OpenAI vision (PDF in, structured data out).

Sends an uploaded bank-statement PDF to an OpenAI vision-capable model and parses
a structured result: the account summary (account number, sort code, period,
opening/closing balance) and the transaction lines (date, description, money
out/in, running balance). All money is parsed to integer minor units (pence) —
never floats.

A reconciliation check verifies that opening balance + net movement == closing
balance, so the caller can flag a low-confidence extraction.

The OpenAI call is wrapped behind ``_call_model`` so tests can inject a fake.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol


class StatementExtractionError(Exception):
    """Extraction failed (model error, unparseable output, etc.)."""


class OcrUnavailableError(StatementExtractionError):
    """OCR is not configured (no API key)."""


@dataclass(frozen=True)
class StatementLine:
    """One transaction row from the statement (amounts in minor units)."""

    date: str | None
    description: str
    money_out_minor: int
    money_in_minor: int
    balance_minor: int | None


@dataclass(frozen=True)
class StatementSummary:
    """Statement-level metadata (amounts in minor units)."""

    account_name: str | None = None
    account_number: str | None = None
    sort_code: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    opening_balance_minor: int | None = None
    closing_balance_minor: int | None = None


@dataclass(frozen=True)
class ExtractedStatement:
    """The full extraction result."""

    summary: StatementSummary
    lines: list[StatementLine] = field(default_factory=list)
    reconciled: bool = False
    currency: str = "GBP"


class ModelClient(Protocol):
    """Minimal interface for the model call (so tests can inject a fake)."""

    def extract(self, *, pdf_bytes: bytes, model: str) -> dict[str, Any]: ...


def _to_minor(value: object) -> int | None:
    """Parse a money value (number or string like '1,234.56') to minor units."""
    if value is None or value == "":
        return None
    try:
        text = str(value).replace(",", "").replace("£", "").replace("$", "").strip()
        if text == "":
            return None
        dec = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return int((dec * 100).to_integral_value())


def _normalize_date(value: object) -> str | None:
    """Best-effort normalize a date to ISO (YYYY-MM-DD); pass through if unknown."""
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y", "%d/%m/%y"):
        try:
            return dt.datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return text


def parse_extraction(payload: dict[str, Any]) -> ExtractedStatement:
    """Turn the model's JSON payload into a typed ExtractedStatement.

    Pure and deterministic — the heart of the parsing, tested without any API.
    """
    raw_summary = payload.get("summary", {}) if isinstance(payload, dict) else {}
    summary = StatementSummary(
        account_name=(raw_summary.get("account_name") or None),
        account_number=(raw_summary.get("account_number") or None),
        sort_code=(raw_summary.get("sort_code") or None),
        period_start=_normalize_date(raw_summary.get("period_start")),
        period_end=_normalize_date(raw_summary.get("period_end")),
        opening_balance_minor=_to_minor(raw_summary.get("opening_balance")),
        closing_balance_minor=_to_minor(raw_summary.get("closing_balance")),
    )

    lines: list[StatementLine] = []
    for raw in payload.get("lines", []) if isinstance(payload, dict) else []:
        if not isinstance(raw, dict):
            continue
        lines.append(
            StatementLine(
                date=_normalize_date(raw.get("date")),
                description=str(raw.get("description") or "").strip(),
                money_out_minor=_to_minor(raw.get("money_out")) or 0,
                money_in_minor=_to_minor(raw.get("money_in")) or 0,
                balance_minor=_to_minor(raw.get("balance")),
            )
        )

    reconciled = _reconciles(summary, lines)
    raw_currency = payload.get("currency") if isinstance(payload, dict) else None
    currency = str(raw_currency or "GBP")[:3].upper()
    return ExtractedStatement(
        summary=summary, lines=lines, reconciled=reconciled, currency=currency
    )


def _reconciles(summary: StatementSummary, lines: list[StatementLine]) -> bool:
    """opening + (sum money_in - sum money_out) == closing, when both balances known."""
    if summary.opening_balance_minor is None or summary.closing_balance_minor is None:
        return False
    net = sum(ln.money_in_minor - ln.money_out_minor for ln in lines)
    return summary.opening_balance_minor + net == summary.closing_balance_minor


# The instruction sent to the model. Kept explicit about minor-unit-free output
# (the model returns human numbers; we convert to minor units ourselves).
_EXTRACTION_PROMPT = (
    "You are extracting data from a UK bank statement PDF. Return ONLY a JSON "
    "object with this exact shape (no markdown, no commentary):\n"
    "{\n"
    '  "currency": "GBP",\n'
    '  "summary": {\n'
    '    "account_name": string|null, "account_number": string|null,\n'
    '    "sort_code": string|null, "period_start": string|null,\n'
    '    "period_end": string|null, "opening_balance": number|null,\n'
    '    "closing_balance": number|null\n'
    "  },\n"
    '  "lines": [\n'
    '    {"date": string, "description": string, "money_out": number|null,\n'
    '     "money_in": number|null, "balance": number|null}\n'
    "  ]\n"
    "}\n"
    "Money values are plain numbers in major units (e.g. 1234.56). Use money_out "
    "for debits/withdrawals and money_in for credits/deposits. Dates as written. "
    "Include every transaction row in order. Do not invent data; use null when "
    "a value is absent."
)


class OpenAIStatementClient:
    """ModelClient backed by the OpenAI Responses API with a PDF input."""

    def __init__(self, api_key: str) -> None:
        # Imported lazily so the package import does not require the SDK unless
        # extraction is actually used.
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key)

    def extract(self, *, pdf_bytes: bytes, model: str) -> dict[str, Any]:
        data_url = "data:application/pdf;base64," + base64.b64encode(pdf_bytes).decode("ascii")
        response = self._client.responses.create(
            model=model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": _EXTRACTION_PROMPT},
                        {
                            "type": "input_file",
                            "filename": "statement.pdf",
                            "file_data": data_url,
                        },
                    ],
                }
            ],
        )
        text = response.output_text
        return _loads_json(text)


def _loads_json(text: str) -> dict[str, Any]:
    """Parse model output as JSON, tolerating accidental markdown fences."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        # Drop an optional leading 'json' language tag.
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1:
        msg = "Model did not return JSON"
        raise StatementExtractionError(msg)
    try:
        result = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        msg = f"Could not parse model JSON: {exc}"
        raise StatementExtractionError(msg) from exc
    if not isinstance(result, dict):
        msg = "Model JSON was not an object"
        raise StatementExtractionError(msg)
    return result


def extract_statement(
    *, pdf_bytes: bytes, model: str, client: ModelClient
) -> ExtractedStatement:
    """Run extraction end-to-end: call the model, then parse to typed data."""
    payload = client.extract(pdf_bytes=pdf_bytes, model=model)
    return parse_extraction(payload)
