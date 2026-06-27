"""Payroll models: employees and payslips.

An employee carries the data a pay run needs (salary, tax code, NI category, pay
frequency). Running payroll for a period computes each employee's pay via the
engine, records a payslip, and posts the wages journal. A unique (employee,
period) on payslips makes a run idempotent — the same period can't be paid twice.

Amounts are integer minor units (pence). Payroll maths lives in the engine.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import BigInteger, Boolean, Date, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ledgerline_backend.db.base import AuditableBase


class Employee(AuditableBase):
    """An employee on a company's payroll."""

    __tablename__ = "employees"

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Annual gross salary in minor units.
    annual_salary_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tax_code: Mapped[str] = mapped_column(String(16), nullable=False, default="1257L")
    ni_category: Mapped[str] = mapped_column(String(2), nullable=False, default="A")
    # 'monthly' | 'weekly' (mirrors engine PayFrequency).
    pay_frequency: Mapped[str] = mapped_column(String(10), nullable=False, default="monthly")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Payslip(AuditableBase):
    """One employee's pay for one period (the breakdown the engine produced)."""

    __tablename__ = "payslips"
    __table_args__ = (
        UniqueConstraint("employee_id", "period_label", name="uq_payslip_employee_period"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # A label identifying the pay period, e.g. '2026-06' (monthly) or '2026-W23'.
    period_label: Mapped[str] = mapped_column(String(16), nullable=False)
    pay_date: Mapped[dt.date] = mapped_column(Date, nullable=False)

    gross_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    income_tax_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    employee_ni_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    employer_ni_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    net_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # The wages journal this payslip posted.
    journal_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
