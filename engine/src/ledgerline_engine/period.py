"""Accounting period and its lock state machine (AC-02).

A period moves OPEN → SOFT_CLOSED → LOCKED. Posting is allowed only while OPEN;
a SOFT_CLOSED period blocks new postings but can be reopened; a LOCKED period is
final and the only correction route is a reversing entry in an open period.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import Enum


class PeriodStatus(Enum):
    """Lifecycle states of an accounting period."""

    OPEN = "open"
    SOFT_CLOSED = "soft_closed"
    LOCKED = "locked"


# Legal transitions: from -> allowed targets.
_TRANSITIONS: dict[PeriodStatus, frozenset[PeriodStatus]] = {
    PeriodStatus.OPEN: frozenset({PeriodStatus.SOFT_CLOSED, PeriodStatus.LOCKED}),
    PeriodStatus.SOFT_CLOSED: frozenset({PeriodStatus.OPEN, PeriodStatus.LOCKED}),
    PeriodStatus.LOCKED: frozenset(),  # terminal
}


class IllegalPeriodTransitionError(Exception):
    """Raised when an illegal period status transition is attempted."""


@dataclass(frozen=True, slots=True)
class Period:
    """A fiscal period with a status. Immutable; transitions return a new Period."""

    fiscal_year: int
    starts_on: dt.date
    ends_on: dt.date
    status: PeriodStatus = PeriodStatus.OPEN

    def __post_init__(self) -> None:
        if self.ends_on <= self.starts_on:
            msg = "Period ends_on must be after starts_on"
            raise ValueError(msg)

    @property
    def accepts_postings(self) -> bool:
        """Only OPEN periods accept new postings."""
        return self.status is PeriodStatus.OPEN

    def contains(self, date: dt.date) -> bool:
        return self.starts_on <= date <= self.ends_on

    def transition_to(self, target: PeriodStatus) -> Period:
        """Return a new Period in ``target`` status, or raise if illegal."""
        if target not in _TRANSITIONS[self.status]:
            msg = f"Cannot transition period from {self.status.value} to {target.value}"
            raise IllegalPeriodTransitionError(msg)
        return Period(
            fiscal_year=self.fiscal_year,
            starts_on=self.starts_on,
            ends_on=self.ends_on,
            status=target,
        )
