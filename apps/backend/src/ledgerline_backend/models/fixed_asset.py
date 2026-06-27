"""Fixed-asset register model.

A fixed asset is depreciated over time; running depreciation for a period posts a
journal (Dr depreciation expense, Cr accumulated depreciation). The asset stores
its cost, residual, method and rate/life, the three GL accounts it touches, and
the depreciation accumulated so far + the last period index depreciated (so a
run is idempotent per period).

Amounts are integer minor units (pence). Depreciation maths lives in the engine.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import BigInteger, Boolean, Date, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from ledgerline_backend.db.base import AuditableBase


class FixedAsset(AuditableBase):
    """A depreciable fixed asset in a company's register."""

    __tablename__ = "fixed_assets"

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    acquired_on: Mapped[dt.date] = mapped_column(Date, nullable=False)

    cost_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    residual_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # 'straight_line' | 'reducing_balance' (mirrors engine DepreciationMethod).
    method: Mapped[str] = mapped_column(String(20), nullable=False)
    # Straight line uses useful_life_periods; reducing balance uses rate_percent.
    useful_life_periods: Mapped[int | None] = mapped_column(nullable=True)
    rate_percent: Mapped[float | None] = mapped_column(Numeric(6, 3), nullable=True)

    # GL accounts the depreciation journal touches.
    asset_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chart_of_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    accumulated_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chart_of_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    expense_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chart_of_accounts.id", ondelete="RESTRICT"), nullable=False
    )

    # Running depreciation state.
    accumulated_depreciation_minor: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    periods_depreciated: Mapped[int] = mapped_column(nullable=False, default=0)
    disposed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
