"""Tests for the Period model and its lock state machine."""

from __future__ import annotations

import datetime as dt

import pytest

from ledgerline_engine.period import (
    IllegalPeriodTransitionError,
    Period,
    PeriodStatus,
)


def _period(status: PeriodStatus = PeriodStatus.OPEN) -> Period:
    return Period(2026, dt.date(2026, 4, 6), dt.date(2027, 4, 5), status)


def test_invalid_dates_rejected() -> None:
    with pytest.raises(ValueError, match="after"):
        Period(2026, dt.date(2026, 4, 6), dt.date(2026, 4, 6))


def test_open_accepts_postings() -> None:
    assert _period(PeriodStatus.OPEN).accepts_postings is True
    assert _period(PeriodStatus.SOFT_CLOSED).accepts_postings is False
    assert _period(PeriodStatus.LOCKED).accepts_postings is False


def test_contains() -> None:
    p = _period()
    assert p.contains(dt.date(2026, 6, 18))
    assert not p.contains(dt.date(2025, 1, 1))


def test_legal_transitions() -> None:
    open_p = _period(PeriodStatus.OPEN)
    soft = open_p.transition_to(PeriodStatus.SOFT_CLOSED)
    assert soft.status is PeriodStatus.SOFT_CLOSED
    # Soft-closed can reopen.
    assert soft.transition_to(PeriodStatus.OPEN).status is PeriodStatus.OPEN
    # Either can lock.
    assert open_p.transition_to(PeriodStatus.LOCKED).status is PeriodStatus.LOCKED


def test_locked_is_terminal() -> None:
    locked = _period(PeriodStatus.LOCKED)
    for target in (PeriodStatus.OPEN, PeriodStatus.SOFT_CLOSED, PeriodStatus.LOCKED):
        with pytest.raises(IllegalPeriodTransitionError):
            locked.transition_to(target)


def test_transition_returns_new_period() -> None:
    p = _period(PeriodStatus.OPEN)
    p2 = p.transition_to(PeriodStatus.LOCKED)
    assert p.status is PeriodStatus.OPEN  # original unchanged
    assert p2.status is PeriodStatus.LOCKED
