"""Payroll endpoints: employees, pay runs, and payslips.

Company-scoped, RBAC-enforced: read = any member; create employees and run
payroll = bookkeeper+ (a run posts a wages journal). Payroll maths is the
engine's; the run posts one balanced journal for the whole period.
"""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from ledgerline_backend.api.membership_deps import ReadMembership, WriteMembership
from ledgerline_backend.dependencies import CurrentUserDep, SessionDep
from ledgerline_backend.services.payroll_service import (
    EmployeeView,
    GLAccountInvalidError,
    InvalidEmployeeError,
    NoEmployeesError,
    PayrollService,
    PayslipView,
    PeriodAlreadyRunError,
)

router = APIRouter(prefix="/companies/{company_id}/payroll", tags=["payroll"])

_NI_CATEGORIES = {"A", "X"}
_FREQUENCIES = {"monthly", "weekly"}


class CreateEmployeeRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    annual_salary_minor: int = Field(ge=0)
    tax_code: str = Field(default="1257L", max_length=16)
    ni_category: str = Field(default="A")
    pay_frequency: str = Field(default="monthly")


class RunPayrollRequest(BaseModel):
    period_label: str = Field(min_length=1, max_length=16)
    pay_date: dt.date
    wages_account_id: uuid.UUID
    employer_ni_account_id: uuid.UUID
    liability_account_id: uuid.UUID
    net_pay_account_id: uuid.UUID


class EmployeeResponse(BaseModel):
    id: uuid.UUID
    name: str
    annual_salary_minor: int
    tax_code: str
    ni_category: str
    pay_frequency: str
    active: bool


class PayslipResponse(BaseModel):
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


class PayRunResponse(BaseModel):
    period_label: str
    journal_id: uuid.UUID
    payslips: list[PayslipResponse]
    total_gross_minor: int
    total_net_minor: int


def _employee_response(v: EmployeeView) -> EmployeeResponse:
    return EmployeeResponse(
        id=v.id,
        name=v.name,
        annual_salary_minor=v.annual_salary_minor,
        tax_code=v.tax_code,
        ni_category=v.ni_category,
        pay_frequency=v.pay_frequency,
        active=v.active,
    )


def _payslip_response(v: PayslipView) -> PayslipResponse:
    return PayslipResponse(
        id=v.id,
        employee_id=v.employee_id,
        employee_name=v.employee_name,
        period_label=v.period_label,
        pay_date=v.pay_date,
        gross_minor=v.gross_minor,
        income_tax_minor=v.income_tax_minor,
        employee_ni_minor=v.employee_ni_minor,
        employer_ni_minor=v.employer_ni_minor,
        net_minor=v.net_minor,
        journal_id=v.journal_id,
    )


@router.get("/employees", response_model=list[EmployeeResponse])
def list_employees(
    company_id: uuid.UUID,
    membership: ReadMembership,
    session: SessionDep,
) -> list[EmployeeResponse]:
    """The company's employees."""
    return [_employee_response(e) for e in PayrollService(session).list_employees(company_id)]


@router.post("/employees", response_model=EmployeeResponse, status_code=status.HTTP_201_CREATED)
def create_employee(
    company_id: uuid.UUID,
    body: CreateEmployeeRequest,
    current_user: CurrentUserDep,
    membership: WriteMembership,
    session: SessionDep,
) -> EmployeeResponse:
    """Add an employee to the payroll (bookkeeper+)."""
    if body.ni_category not in _NI_CATEGORIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown NI category {body.ni_category!r}",
        )
    if body.pay_frequency not in _FREQUENCIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown pay frequency {body.pay_frequency!r}",
        )
    try:
        employee = PayrollService(session).create_employee(
            actor_id=current_user.id,
            company_id=company_id,
            name=body.name,
            annual_salary_minor=body.annual_salary_minor,
            tax_code=body.tax_code,
            ni_category=body.ni_category,
            pay_frequency=body.pay_frequency,
        )
    except InvalidEmployeeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return _employee_response(employee)


@router.get("/payslips", response_model=list[PayslipResponse])
def list_payslips(
    company_id: uuid.UUID,
    membership: ReadMembership,
    session: SessionDep,
) -> list[PayslipResponse]:
    """All payslips for the company (most recent period first)."""
    return [_payslip_response(p) for p in PayrollService(session).list_payslips(company_id)]


@router.post("/runs", response_model=PayRunResponse, status_code=status.HTTP_201_CREATED)
def run_payroll(
    company_id: uuid.UUID,
    body: RunPayrollRequest,
    current_user: CurrentUserDep,
    membership: WriteMembership,
    session: SessionDep,
) -> PayRunResponse:
    """Run payroll for a period, posting the wages journal (bookkeeper+)."""
    try:
        result = PayrollService(session).run_period(
            actor_id=current_user.id,
            company_id=company_id,
            period_label=body.period_label,
            pay_date=body.pay_date,
            wages_account_id=body.wages_account_id,
            employer_ni_account_id=body.employer_ni_account_id,
            liability_account_id=body.liability_account_id,
            net_pay_account_id=body.net_pay_account_id,
        )
    except PeriodAlreadyRunError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except GLAccountInvalidError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A chosen general-ledger account is invalid",
        ) from exc
    except NoEmployeesError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return PayRunResponse(
        period_label=result.period_label,
        journal_id=result.journal_id,
        payslips=[_payslip_response(p) for p in result.payslips],
        total_gross_minor=result.total_gross_minor,
        total_net_minor=result.total_net_minor,
    )
