"""Accounting period service.

Creates fiscal periods, transitions their lock status (open -> soft_closed ->
locked) using the canonical engine state machine, and answers whether a given
date is postable (its containing period must be OPEN, or have no period at all).

The posting service consults ``assert_date_postable`` so a journal can never be
posted into a soft-closed or locked period.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

from ledgerline_engine.api import (
    IllegalPeriodTransitionError,
    Period,
    PeriodStatus,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from ledgerline_backend.models import AccountingPeriod
from ledgerline_backend.services.audit import record_audit


class PeriodError(Exception):
    """Base class for period failures."""


class PeriodNotFoundError(PeriodError):
    """No such period in the company."""


class PeriodOverlapError(PeriodError):
    """The new period overlaps an existing one."""


class InvalidPeriodError(PeriodError):
    """The period dates are invalid."""


class PeriodLockedError(PeriodError):
    """The date falls in a soft-closed or locked period; posting is blocked."""

    def __init__(self, period_name: int, status: str) -> None:
        super().__init__(
            f"Period {period_name} is {status}; posting into it is not allowed"
        )
        self.period_name = period_name
        self.status = status


@dataclass(frozen=True)
class PeriodView:
    id: uuid.UUID
    fiscal_year: int
    starts_on: dt.date
    ends_on: dt.date
    status: str


def _to_status(value: str) -> PeriodStatus:
    return PeriodStatus(value)


class PeriodService:
    """Fiscal periods and their lock status for a company."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def _view(self, period: AccountingPeriod) -> PeriodView:
        return PeriodView(
            id=period.id,
            fiscal_year=period.fiscal_year,
            starts_on=period.starts_on,
            ends_on=period.ends_on,
            status=period.status,
        )

    def list_periods(self, company_id: uuid.UUID) -> list[PeriodView]:
        rows = self._session.scalars(
            select(AccountingPeriod)
            .where(AccountingPeriod.company_id == company_id)
            .order_by(AccountingPeriod.starts_on)
        ).all()
        return [self._view(p) for p in rows]

    def create(
        self,
        *,
        actor_id: uuid.UUID,
        company_id: uuid.UUID,
        fiscal_year: int,
        starts_on: dt.date,
        ends_on: dt.date,
    ) -> PeriodView:
        if ends_on <= starts_on:
            raise InvalidPeriodError("Period end must be after its start")
        # Reject overlaps with existing periods.
        existing = self._session.scalars(
            select(AccountingPeriod).where(AccountingPeriod.company_id == company_id)
        ).all()
        for other in existing:
            if starts_on <= other.ends_on and other.starts_on <= ends_on:
                raise PeriodOverlapError(
                    f"Overlaps period {other.fiscal_year}"
                )
        period = AccountingPeriod(
            company_id=company_id,
            fiscal_year=fiscal_year,
            starts_on=starts_on,
            ends_on=ends_on,
            status="open",
        )
        self._session.add(period)
        self._session.flush()
        record_audit(
            self._session,
            entity_type="accounting_period",
            entity_id=period.id,
            action="period_created",
            actor_user_id=actor_id,
            company_id=company_id,
        )
        return self._view(period)

    def set_status(
        self,
        *,
        actor_id: uuid.UUID,
        company_id: uuid.UUID,
        period_id: uuid.UUID,
        target: str,
    ) -> PeriodView:
        """Transition a period's status, validated by the engine state machine."""
        period = self._session.get(AccountingPeriod, period_id)
        if period is None or period.company_id != company_id:
            raise PeriodNotFoundError
        engine_period = Period(
            fiscal_year=period.fiscal_year,
            starts_on=period.starts_on,
            ends_on=period.ends_on,
            status=_to_status(period.status),
        )
        try:
            moved = engine_period.transition_to(_to_status(target))
        except IllegalPeriodTransitionError as exc:
            raise InvalidPeriodError(str(exc)) from exc
        period.status = moved.status.value
        self._session.flush()
        record_audit(
            self._session,
            entity_type="accounting_period",
            entity_id=period.id,
            action=f"period_{moved.status.value}",
            actor_user_id=actor_id,
            company_id=company_id,
        )
        return self._view(period)

    def assert_date_postable(self, company_id: uuid.UUID, date: dt.date) -> None:
        """Raise PeriodLockedError if ``date`` falls in a non-open period.

        Dates not covered by any period are allowed (periods are optional until
        a company starts using them).
        """
        period = self._session.scalar(
            select(AccountingPeriod).where(
                AccountingPeriod.company_id == company_id,
                AccountingPeriod.starts_on <= date,
                AccountingPeriod.ends_on >= date,
            )
        )
        if period is not None and period.status != "open":
            raise PeriodLockedError(period.fiscal_year, period.status)
