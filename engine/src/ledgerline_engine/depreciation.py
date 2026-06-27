"""Depreciation schedules for fixed assets.

Computes the per-period depreciation charge for an asset under the two common
methods:

* STRAIGHT_LINE — (cost - residual) spread evenly over the useful life.
* REDUCING_BALANCE — a fixed percentage of the *remaining* net book value each
  period.

All amounts are integer minor units (pence); charges are rounded HALF_UP (the
HMRC convention). A schedule never depreciates an asset below its residual value
and stops once fully depreciated. Pure and deterministic — no I/O, no dates
beyond a period index, so it runs identically in the backend and a future
Electron sidecar.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum


class DepreciationMethod(Enum):
    STRAIGHT_LINE = "straight_line"
    REDUCING_BALANCE = "reducing_balance"


class DepreciationError(Exception):
    """Invalid depreciation parameters."""


@dataclass(frozen=True)
class DepreciationLine:
    """One period's depreciation outcome."""

    period_index: int  # 1-based period number since acquisition
    charge_minor: int  # depreciation expense for this period
    accumulated_minor: int  # total depreciation to date (inclusive)
    net_book_value_minor: int  # cost - accumulated


@dataclass(frozen=True)
class FixedAssetSpec:
    """The inputs that determine an asset's depreciation schedule."""

    cost_minor: int
    residual_minor: int
    method: DepreciationMethod
    # Straight line uses useful_life_periods; reducing balance uses rate_percent.
    useful_life_periods: int | None = None
    rate_percent: Decimal | None = None

    def __post_init__(self) -> None:
        if self.cost_minor < 0 or self.residual_minor < 0:
            raise DepreciationError("Cost and residual must be non-negative")
        if self.residual_minor > self.cost_minor:
            raise DepreciationError("Residual cannot exceed cost")
        if self.method is DepreciationMethod.STRAIGHT_LINE:
            if self.useful_life_periods is None or self.useful_life_periods <= 0:
                raise DepreciationError("Straight line needs a positive useful life")
        elif self.method is DepreciationMethod.REDUCING_BALANCE:
            if self.rate_percent is None or not (Decimal(0) < self.rate_percent <= Decimal(100)):
                raise DepreciationError("Reducing balance needs a rate in (0, 100]")


def _round_half_up(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def period_charge(
    spec: FixedAssetSpec, *, accumulated_minor: int, period_index: int = 0
) -> int:
    """The depreciation charge for a period given accumulated-to-date.

    Returns 0 once the asset has reached its residual value. ``period_index`` is
    1-based; for straight line the final period absorbs any rounding remainder so
    the asset lands exactly on its residual over ``useful_life_periods`` periods.
    The charge is always clamped so net book value never drops below residual.
    """
    nbv = spec.cost_minor - accumulated_minor
    depreciable_remaining = nbv - spec.residual_minor
    if depreciable_remaining <= 0:
        return 0

    if spec.method is DepreciationMethod.STRAIGHT_LINE:
        if spec.useful_life_periods is None:  # pragma: no cover - guarded in __post_init__
            raise DepreciationError("Straight line needs a useful life")
        depreciable = spec.cost_minor - spec.residual_minor
        per_period = _round_half_up(Decimal(depreciable) / Decimal(spec.useful_life_periods))
        # The last scheduled period takes whatever is left, clearing rounding.
        charge = depreciable_remaining if period_index >= spec.useful_life_periods else per_period
    else:
        if spec.rate_percent is None:  # pragma: no cover - guarded in __post_init__
            raise DepreciationError("Reducing balance needs a rate")
        charge = _round_half_up(Decimal(nbv) * spec.rate_percent / Decimal(100))

    # Never depreciate past the residual value.
    return min(charge, depreciable_remaining)


def schedule(spec: FixedAssetSpec, *, max_periods: int = 600) -> list[DepreciationLine]:
    """Full depreciation schedule until the asset reaches its residual value.

    ``max_periods`` is a safety bound (50 years monthly) so a tiny reducing-
    balance rate cannot loop forever; the schedule normally ends earlier.
    """
    lines: list[DepreciationLine] = []
    accumulated = 0
    for i in range(1, max_periods + 1):
        charge = period_charge(spec, accumulated_minor=accumulated, period_index=i)
        if charge == 0:
            break
        accumulated += charge
        lines.append(
            DepreciationLine(
                period_index=i,
                charge_minor=charge,
                accumulated_minor=accumulated,
                net_book_value_minor=spec.cost_minor - accumulated,
            )
        )
    return lines
