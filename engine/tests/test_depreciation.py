"""Tests for the fixed-asset depreciation engine."""

from __future__ import annotations

from decimal import Decimal

import pytest

from ledgerline_engine.depreciation import (
    DepreciationError,
    DepreciationMethod,
    FixedAssetSpec,
    period_charge,
    schedule,
)


def test_straight_line_spreads_evenly() -> None:
    # 1200.00 cost, no residual, 12 periods -> 100.00 each.
    spec = FixedAssetSpec(
        cost_minor=120000,
        residual_minor=0,
        method=DepreciationMethod.STRAIGHT_LINE,
        useful_life_periods=12,
    )
    lines = schedule(spec)
    assert len(lines) == 12
    assert all(line.charge_minor == 10000 for line in lines)
    assert lines[-1].accumulated_minor == 120000
    assert lines[-1].net_book_value_minor == 0


def test_straight_line_respects_residual() -> None:
    # 1000.00 cost, 100.00 residual, 9 periods -> depreciable 900.00 / 9 = 100.00.
    spec = FixedAssetSpec(
        cost_minor=100000,
        residual_minor=10000,
        method=DepreciationMethod.STRAIGHT_LINE,
        useful_life_periods=9,
    )
    lines = schedule(spec)
    assert sum(line.charge_minor for line in lines) == 90000
    assert lines[-1].net_book_value_minor == 10000  # never below residual


def test_straight_line_final_period_clamps_rounding() -> None:
    # 100.00 over 3 periods: 33.33, 33.33, then 33.34 to land exactly on 0.
    spec = FixedAssetSpec(
        cost_minor=10000,
        residual_minor=0,
        method=DepreciationMethod.STRAIGHT_LINE,
        useful_life_periods=3,
    )
    lines = schedule(spec)
    assert [line.charge_minor for line in lines] == [3333, 3333, 3334]
    assert lines[-1].net_book_value_minor == 0


def test_reducing_balance_takes_percentage_of_nbv() -> None:
    # 1000.00 at 25% -> 250.00 then 187.50 (of 750.00) ...
    spec = FixedAssetSpec(
        cost_minor=100000,
        residual_minor=0,
        method=DepreciationMethod.REDUCING_BALANCE,
        rate_percent=Decimal(25),
    )
    first = period_charge(spec, accumulated_minor=0)
    assert first == 25000
    second = period_charge(spec, accumulated_minor=25000)
    assert second == 18750  # 25% of 750.00


def test_reducing_balance_stops_at_residual() -> None:
    spec = FixedAssetSpec(
        cost_minor=100000,
        residual_minor=20000,
        method=DepreciationMethod.REDUCING_BALANCE,
        rate_percent=Decimal(50),
    )
    lines = schedule(spec)
    # Never drops below the 200.00 residual.
    assert lines[-1].net_book_value_minor >= 20000
    # Once at residual, no further charge.
    assert period_charge(spec, accumulated_minor=lines[-1].accumulated_minor) == 0


def test_no_charge_when_already_fully_depreciated() -> None:
    spec = FixedAssetSpec(
        cost_minor=50000,
        residual_minor=0,
        method=DepreciationMethod.STRAIGHT_LINE,
        useful_life_periods=5,
    )
    assert period_charge(spec, accumulated_minor=50000) == 0


def test_invalid_specs_raise() -> None:
    with pytest.raises(DepreciationError):
        FixedAssetSpec(
            cost_minor=1000,
            residual_minor=2000,  # residual > cost
            method=DepreciationMethod.STRAIGHT_LINE,
            useful_life_periods=5,
        )
    with pytest.raises(DepreciationError):
        FixedAssetSpec(
            cost_minor=1000,
            residual_minor=0,
            method=DepreciationMethod.STRAIGHT_LINE,
            useful_life_periods=0,  # non-positive life
        )
    with pytest.raises(DepreciationError):
        FixedAssetSpec(
            cost_minor=1000,
            residual_minor=0,
            method=DepreciationMethod.REDUCING_BALANCE,
            rate_percent=Decimal(0),  # rate must be > 0
        )


def test_public_api_exposes_depreciation() -> None:
    from ledgerline_engine import api

    spec = api.FixedAssetSpec(
        cost_minor=120000,
        residual_minor=0,
        method=api.DepreciationMethod.STRAIGHT_LINE,
        useful_life_periods=12,
    )
    assert api.period_charge(spec, accumulated_minor=0) == 10000
    assert len(api.schedule(spec)) == 12
