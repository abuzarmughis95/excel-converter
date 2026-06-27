"""Tests for the Money value type, including float-drift property tests."""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ledgerline_engine.money import Money, Rounding, sum_money


def test_construct_from_minor_units() -> None:
    m = Money(12345, "GBP")
    assert m.minor_units == 12345
    assert m.currency == "GBP"


def test_rejects_non_int_minor_units() -> None:
    with pytest.raises(TypeError):
        Money(10.5, "GBP")  # type: ignore[arg-type]


def test_rejects_bool_minor_units() -> None:
    # bool is a subclass of int; must be rejected explicitly.
    with pytest.raises(TypeError):
        Money(True, "GBP")  # type: ignore[arg-type]


def test_rejects_invalid_currency() -> None:
    for bad in ("gbp", "POUND", "G2P", "12"):
        with pytest.raises(ValueError, match="currency"):
            Money(100, bad)


def test_zero() -> None:
    assert Money.zero("GBP").is_zero


def test_of_major_scales_and_rounds() -> None:
    assert Money.of_major("12.34", "GBP").minor_units == 1234
    assert Money.of_major("12.345", "GBP").minor_units == 1235  # half-up
    assert Money.of_major("0.1", "GBP").minor_units == 10


def test_of_major_accepts_decimal() -> None:
    assert Money.of_major(Decimal("9.99"), "GBP").minor_units == 999


def test_addition_is_exact_no_float_drift() -> None:
    # The classic 0.1 + 0.2 case: in pence it is exact.
    assert (Money(10, "GBP") + Money(20, "GBP")).minor_units == 30


def test_subtraction() -> None:
    assert (Money(100, "GBP") - Money(30, "GBP")).minor_units == 70


def test_negate_and_abs() -> None:
    assert (-Money(500, "GBP")).minor_units == -500
    assert abs(Money(-500, "GBP")).minor_units == 500


def test_currency_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="Currency mismatch"):
        Money(100, "GBP") + Money(100, "USD")


def test_percentage_rounds_once_half_up() -> None:
    # 20% VAT on £1.00 (100p) = 20p.
    assert Money(100, "GBP").percentage(Decimal("0.20")).minor_units == 20
    # 20% of 12.5p rounds half-up to 3 (2.5 -> 3).
    assert Money(125, "GBP").percentage(Decimal("0.02")).minor_units == 3


def test_multiply_by_fx_rate() -> None:
    # 100 units * 1.2345, rounded half-up.
    assert Money(100, "GBP").multiply(Decimal("1.2345")).minor_units == 123


def test_sign() -> None:
    assert Money(5, "GBP").sign == 1
    assert Money(-5, "GBP").sign == -1
    assert Money(0, "GBP").sign == 0


def test_str() -> None:
    assert str(Money(123456, "GBP")) == "1234.56 GBP"
    assert str(Money(-50, "GBP")) == "-0.50 GBP"


def test_sum_money() -> None:
    total = sum_money([Money(100, "GBP"), Money(250, "GBP"), Money(-50, "GBP")])
    assert total.minor_units == 300


def test_sum_empty_requires_currency() -> None:
    assert sum_money([], "GBP").minor_units == 0
    with pytest.raises(ValueError, match="empty list"):
        sum_money([])


def test_equality_and_hash() -> None:
    assert Money(100, "GBP") == Money(100, "GBP")
    assert Money(100, "GBP") != Money(100, "USD")
    assert len({Money(100, "GBP"), Money(100, "GBP")}) == 1


# -- property-based tests --------------------------------------------------

_amounts = st.integers(min_value=-10**12, max_value=10**12)


@given(a=_amounts, b=_amounts, c=_amounts)
def test_addition_is_associative(a: int, b: int, c: int) -> None:
    ma, mb, mc = Money(a, "GBP"), Money(b, "GBP"), Money(c, "GBP")
    assert (ma + mb) + mc == ma + (mb + mc)


@given(a=_amounts, b=_amounts)
def test_addition_is_commutative(a: int, b: int) -> None:
    assert Money(a, "GBP") + Money(b, "GBP") == Money(b, "GBP") + Money(a, "GBP")


@given(a=_amounts)
def test_subtract_self_is_zero(a: int) -> None:
    assert (Money(a, "GBP") - Money(a, "GBP")).is_zero


@given(values=st.lists(_amounts, min_size=1, max_size=50))
def test_sum_matches_manual_total(values: list[int]) -> None:
    monies = [Money(v, "GBP") for v in values]
    assert sum_money(monies).minor_units == sum(values)


def test_rounding_half_even_available() -> None:
    # 2.5 -> 2 under banker's rounding, 3 under half-up.
    assert Money(125, "GBP").percentage(
        Decimal("0.02"), rounding=Rounding.HALF_EVEN
    ).minor_units == 2
    assert Money(125, "GBP").percentage(
        Decimal("0.02"), rounding=Rounding.HALF_UP
    ).minor_units == 3
