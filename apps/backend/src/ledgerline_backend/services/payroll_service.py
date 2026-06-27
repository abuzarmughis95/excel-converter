"""Payroll service.

Manages employees and runs payroll for a period: it computes each active
employee's pay via the engine, records a payslip per employee, and posts a single
balanced wages journal for the run:

    Dr Wages expense            (total gross)
    Dr Employer NI expense      (total employer NI)
        Cr PAYE/NI liability    (total income tax + employee NI + employer NI)
        Cr Net pay liability    (total net pay)

This balances because net = gross - tax - employee NI. A run is idempotent per
period via a unique (employee, period_label): paying the same period twice is
rejected before any journal is posted.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

from ledgerline_engine.api import (
    NiCategory,
    PayComponents,
    PayFrequency,
    compute_pay,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from ledgerline_backend.models import ChartOfAccount, Employee, Payslip
from ledgerline_backend.services.audit import record_audit
from ledgerline_backend.services.posting_service import LineInput, PostingService


class PayrollError(Exception):
    """Base class for payroll failures."""


class EmployeeNotFoundError(PayrollError):
    """No such employee in the company."""


class InvalidEmployeeError(PayrollError):
    """The employee's parameters are invalid."""


class GLAccountInvalidError(PayrollError):
    """A referenced GL account is missing or in the wrong company."""


class PeriodAlreadyRunError(PayrollError):
    """One or more employees have already been paid for this period."""


class NoEmployeesError(PayrollError):
    """There are no active employees to pay."""


@dataclass(frozen=True)
class EmployeeView:
    id: uuid.UUID
    name: str
    annual_salary_minor: int
    tax_code: str
    ni_category: str
    pay_frequency: str
    active: bool


@dataclass(frozen=True)
class PayslipView:
    id: uuid.UUID
    employee_id: uuid.UUID
    employee_name: str
    period_label: str
    pay_date: dt.date
    gross_minor: int
    income_tax_minor: int
    employee_ni_minor: int
    employer_ni_minor: int
    net_minor: int
    journal_id: uuid.UUID | None


@dataclass(frozen=True)
class PayRunResult:
    period_label: str
    journal_id: uuid.UUID
    payslips: list[PayslipView]
    total_gross_minor: int
    total_net_minor: int


class PayrollService:
    """Employee management and pay runs for a company."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # -- employees --------------------------------------------------------

    def _emp_view(self, e: Employee) -> EmployeeView:
        return EmployeeView(
            id=e.id,
            name=e.name,
            annual_salary_minor=e.annual_salary_minor,
            tax_code=e.tax_code,
            ni_category=e.ni_category,
            pay_frequency=e.pay_frequency,
            active=e.active,
        )

    def list_employees(self, company_id: uuid.UUID) -> list[EmployeeView]:
        rows = self._session.scalars(
            select(Employee)
            .where(Employee.company_id == company_id)
            .order_by(Employee.name)
        ).all()
        return [self._emp_view(e) for e in rows]

    def create_employee(
        self,
        *,
        actor_id: uuid.UUID,
        company_id: uuid.UUID,
        name: str,
        annual_salary_minor: int,
        tax_code: str = "1257L",
        ni_category: str = "A",
        pay_frequency: str = "monthly",
    ) -> EmployeeView:
        if not name.strip():
            raise InvalidEmployeeError("Employee name is required")
        if annual_salary_minor < 0:
            raise InvalidEmployeeError("Salary must be non-negative")
        # Validate enums by constructing them.
        try:
            NiCategory(ni_category)
            PayFrequency(pay_frequency)
        except ValueError as exc:
            raise InvalidEmployeeError(str(exc)) from exc

        employee = Employee(
            company_id=company_id,
            name=name.strip(),
            annual_salary_minor=annual_salary_minor,
            tax_code=tax_code.strip().upper(),
            ni_category=ni_category,
            pay_frequency=pay_frequency,
        )
        self._session.add(employee)
        self._session.flush()
        record_audit(
            self._session,
            entity_type="employee",
            entity_id=employee.id,
            action="employee_created",
            actor_user_id=actor_id,
            company_id=company_id,
        )
        return self._emp_view(employee)

    # -- pay run ----------------------------------------------------------

    def list_payslips(self, company_id: uuid.UUID) -> list[PayslipView]:
        rows = self._session.execute(
            select(Payslip, Employee)
            .join(Employee, Employee.id == Payslip.employee_id)
            .where(Payslip.company_id == company_id)
            .order_by(Payslip.period_label.desc(), Employee.name)
        ).all()
        return [self._payslip_view(p, e.name) for p, e in rows]

    def _payslip_view(self, p: Payslip, employee_name: str) -> PayslipView:
        return PayslipView(
            id=p.id,
            employee_id=p.employee_id,
            employee_name=employee_name,
            period_label=p.period_label,
            pay_date=p.pay_date,
            gross_minor=p.gross_minor,
            income_tax_minor=p.income_tax_minor,
            employee_ni_minor=p.employee_ni_minor,
            employer_ni_minor=p.employer_ni_minor,
            net_minor=p.net_minor,
            journal_id=p.journal_id,
        )

    def _require_account(self, company_id: uuid.UUID, account_id: uuid.UUID) -> ChartOfAccount:
        account = self._session.get(ChartOfAccount, account_id)
        if account is None or account.company_id != company_id or not account.is_active:
            raise GLAccountInvalidError("GL account is invalid for this company")
        return account

    def run_period(
        self,
        *,
        actor_id: uuid.UUID,
        company_id: uuid.UUID,
        period_label: str,
        pay_date: dt.date,
        wages_account_id: uuid.UUID,
        employer_ni_account_id: uuid.UUID,
        liability_account_id: uuid.UUID,
        net_pay_account_id: uuid.UUID,
    ) -> PayRunResult:
        """Run payroll for ``period_label``, posting one balanced wages journal."""
        for account_id in (
            wages_account_id,
            employer_ni_account_id,
            liability_account_id,
            net_pay_account_id,
        ):
            self._require_account(company_id, account_id)

        employees = self._session.scalars(
            select(Employee).where(
                Employee.company_id == company_id, Employee.active.is_(True)
            )
        ).all()
        if not employees:
            raise NoEmployeesError("No active employees to pay")

        # Reject if any of these employees already has a payslip for the period.
        already = self._session.scalar(
            select(Payslip).where(
                Payslip.company_id == company_id, Payslip.period_label == period_label
            )
        )
        if already is not None:
            raise PeriodAlreadyRunError(f"Period {period_label} has already been run")

        # Compute everyone first (so a bad employee fails the whole run cleanly).
        computed: list[tuple[Employee, PayComponents]] = []
        total_gross = total_tax = total_ee_ni = total_er_ni = total_net = 0
        for emp in employees:
            freq = PayFrequency(emp.pay_frequency)
            period_gross = emp.annual_salary_minor // freq.periods_per_year
            pay = compute_pay(
                gross_minor=period_gross,
                tax_code=emp.tax_code,
                category=NiCategory(emp.ni_category),
                freq=freq,
            )
            computed.append((emp, pay))
            total_gross += pay.gross_minor
            total_tax += pay.income_tax_minor
            total_ee_ni += pay.employee_ni_minor
            total_er_ni += pay.employer_ni_minor
            total_net += pay.net_minor

        # Post one balanced wages journal for the whole run.
        liability = total_tax + total_ee_ni + total_er_ni
        lines = [
            LineInput(account_id=wages_account_id, debit_minor=total_gross),
            LineInput(account_id=employer_ni_account_id, debit_minor=total_er_ni),
            LineInput(account_id=liability_account_id, credit_minor=liability),
            LineInput(account_id=net_pay_account_id, credit_minor=total_net),
        ]
        posting = PostingService(self._session)
        journal = posting.create(
            actor_id=actor_id,
            company_id=company_id,
            journal_date=pay_date,
            journal_type="payroll",
            narrative=f"Payroll {period_label}",
            lines=lines,
        )
        posting.post(actor_id=actor_id, company_id=company_id, journal_id=journal.id)

        # Record a payslip per employee.
        views: list[PayslipView] = []
        for emp, pay in computed:
            slip = Payslip(
                company_id=company_id,
                employee_id=emp.id,
                period_label=period_label,
                pay_date=pay_date,
                gross_minor=pay.gross_minor,
                income_tax_minor=pay.income_tax_minor,
                employee_ni_minor=pay.employee_ni_minor,
                employer_ni_minor=pay.employer_ni_minor,
                net_minor=pay.net_minor,
                journal_id=journal.id,
            )
            self._session.add(slip)
            self._session.flush()
            views.append(self._payslip_view(slip, emp.name))

        record_audit(
            self._session,
            entity_type="payroll_run",
            entity_id=journal.id,
            action="payroll_run",
            actor_user_id=actor_id,
            company_id=company_id,
        )
        return PayRunResult(
            period_label=period_label,
            journal_id=journal.id,
            payslips=views,
            total_gross_minor=total_gross,
            total_net_minor=total_net,
        )
