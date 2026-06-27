"""Money as integer minor units (AC-01).

Accounting software MUST NOT use floating point for money: 0.1 + 0.2 != 0.3 in
IEEE-754 and such drift is catastrophic in a ledger. ``Money`` stores an integer
number of minor units (e.g. pence) plus an ISO-4217 currency. All arithmetic is
exact integer arithmetic; there is no float path anywhere.

Division and percentage results (VAT, FX) are produced via ``Decimal`` and
rounded exactly once through an explicitly named policy at the point of
computation — never re-derived differently downstream.

This is the authoritative implementation; the TypeScript ``Money`` in
@ledgerline/shared-types mirrors it and both are exercised by the golden vectors.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Final

_CURRENCY_RE: Final = re.compile(r"^[A-Z]{3}$")
# Guardrail against absurd values that would indicate a bug upstream.
_MAX_MINOR_UNITS: Final = 10**18


class Rounding(Enum):
    """Named rounding policies. The policy is always explicit at the call site."""

    HALF_UP = "half_up"  # HMRC default for VAT line computation
    HALF_EVEN = "half_even"  # banker's rounding


def _validate_currency(code: str) -> str:
    if not _CURRENCY_RE.match(code):
        msg = f"Invalid ISO-4217 currency code: {code!r}"
        raise ValueError(msg)
    return code


@dataclass(frozen=True, slots=True)
class Money:
    """An exact monetary amount: integer minor units + ISO-4217 currency.

    Immutable and hashable. Construct via the constructor or :meth:`of`.
    """

    minor_units: int
    currency: str

    def __post_init__(self) -> None:
        if not isinstance(self.minor_units, int) or isinstance(self.minor_units, bool):
            msg = f"minor_units must be an int, got {type(self.minor_units).__name__}"
            raise TypeError(msg)
        if abs(self.minor_units) > _MAX_MINOR_UNITS:
            msg = f"minor_units out of supported range: {self.minor_units}"
            raise ValueError(msg)
        _validate_currency(self.currency)

    # -- constructors -----------------------------------------------------

    @classmethod
    def zero(cls, currency: str) -> Money:
        """Zero in the given currency."""
        return cls(0, currency)

    @classmethod
    def of_major(
        cls,
        major: str | Decimal,
        currency: str,
        *,
        minor_digits: int = 2,
        rounding: Rounding = Rounding.HALF_UP,
    ) -> Money:
        """Build Money from a major-unit decimal string (e.g. '12.34' GBP).

        Strings are preferred over floats to avoid representation error. The
        value is scaled to minor units and rounded once via ``rounding``.
        """
        value = Decimal(major) if isinstance(major, str) else major
        scaled = value * (10**minor_digits)
        minor = int(_apply_rounding(scaled, rounding))
        return cls(minor, currency)

    # -- arithmetic (same currency only) ----------------------------------

    def _check_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            msg = f"Currency mismatch: {self.currency} vs {other.currency}"
            raise ValueError(msg)

    def add(self, other: Money) -> Money:
        self._check_currency(other)
        return Money(self.minor_units + other.minor_units, self.currency)

    def subtract(self, other: Money) -> Money:
        self._check_currency(other)
        return Money(self.minor_units - other.minor_units, self.currency)

    def negate(self) -> Money:
        return Money(-self.minor_units, self.currency)

    def __add__(self, other: Money) -> Money:
        return self.add(other)

    def __sub__(self, other: Money) -> Money:
        return self.subtract(other)

    def __neg__(self) -> Money:
        return self.negate()

    # -- multiplication / percentage (exact, rounded once) ----------------

    def multiply(self, factor: Decimal | int, *, rounding: Rounding = Rounding.HALF_UP) -> Money:
        """Multiply by a factor (e.g. an FX rate or quantity), rounding once."""
        product = Decimal(self.minor_units) * Decimal(factor)
        return Money(int(_apply_rounding(product, rounding)), self.currency)

    def percentage(self, rate: Decimal, *, rounding: Rounding = Rounding.HALF_UP) -> Money:
        """Compute ``rate`` of this amount (e.g. VAT), rounding once.

        ``rate`` is a fraction, e.g. Decimal('0.20') for 20%.
        """
        result = Decimal(self.minor_units) * rate
        return Money(int(_apply_rounding(result, rounding)), self.currency)

    # -- predicates -------------------------------------------------------

    @property
    def is_zero(self) -> bool:
        return self.minor_units == 0

    @property
    def sign(self) -> int:
        if self.minor_units > 0:
            return 1
        if self.minor_units < 0:
            return -1
        return 0

    def __abs__(self) -> Money:
        return Money(abs(self.minor_units), self.currency)

    def __str__(self) -> str:
        sign = "-" if self.minor_units < 0 else ""
        whole, frac = divmod(abs(self.minor_units), 100)
        return f"{sign}{whole}.{frac:02d} {self.currency}"


def _apply_rounding(value: Decimal, rounding: Rounding) -> Decimal:
    mode = ROUND_HALF_UP if rounding is Rounding.HALF_UP else "ROUND_HALF_EVEN"
    return value.quantize(Decimal(1), rounding=mode)


def sum_money(values: list[Money], currency_if_empty: str | None = None) -> Money:
    """Sum a list of same-currency Money values.

    An empty list requires an explicit currency, since the result currency
    cannot otherwise be inferred.
    """
    if not values:
        if currency_if_empty is None:
            msg = "Cannot sum an empty list without an explicit currency"
            raise ValueError(msg)
        return Money.zero(currency_if_empty)
    total = values[0]
    for value in values[1:]:
        total = total.add(value)
    return total
