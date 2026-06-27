"""HMRC MTD-for-VAT service.

Orchestrates the OAuth connection and VAT-return submission for a company:

* the authorize URL the user is redirected to,
* exchanging the returned code for a token (stored per company),
* listing the company's VAT obligations from HMRC,
* submitting a finalised VAT return against an obligation period and storing
  HMRC's receipt on the submission row.

The actual HMRC calls go through an injected ``HmrcClient`` (the real
``HttpHmrcClient`` in production, a fake in tests), so this service is fully
testable without live HMRC access.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ledgerline_backend.models import (
    Company,
    HmrcToken,
    VatReturnSubmission,
)
from ledgerline_backend.services.audit import record_audit
from ledgerline_backend.services.hmrc_client import (
    HmrcClient,
    HmrcError,
    NineBoxReturn,
    VatObligation,
)
from ledgerline_backend.util.time import utcnow


class MtdError(Exception):
    """Base class for MTD failures."""


class MtdNotConfiguredError(MtdError):
    """HMRC credentials are not configured on the server."""


class MtdNotConnectedError(MtdError):
    """The company has not connected its HMRC account (no token)."""


class MtdNoVrnError(MtdError):
    """The company has no VAT registration number."""


class SubmissionNotFoundError(MtdError):
    """No such finalised VAT submission."""


class AlreadySubmittedError(MtdError):
    """The return has already been submitted to HMRC."""


@dataclass(frozen=True)
class SubmitResult:
    submission_id: uuid.UUID
    form_bundle_number: str
    charge_ref_number: str | None
    received_at: dt.datetime


class MtdService:
    """Per-company HMRC MTD operations."""

    def __init__(self, session: Session, client: HmrcClient) -> None:
        self._session = session
        self._client = client

    # -- connection -------------------------------------------------------

    def _vrn(self, company_id: uuid.UUID) -> str:
        company = self._session.get(Company, company_id)
        if company is None or not company.vat_registration_no:
            raise MtdNoVrnError("Company has no VAT registration number")
        # HMRC expects digits only.
        return "".join(c for c in company.vat_registration_no if c.isdigit())

    def store_token(
        self,
        *,
        company_id: uuid.UUID,
        access_token: str,
        refresh_token: str | None,
        expires_in: int,
    ) -> None:
        """Persist the OAuth token for a company (replacing any existing one)."""
        existing = self._session.scalar(
            select(HmrcToken).where(HmrcToken.company_id == company_id)
        )
        expires_at = utcnow() + dt.timedelta(seconds=max(0, expires_in))
        if existing is None:
            self._session.add(
                HmrcToken(
                    company_id=company_id,
                    access_token=access_token,
                    refresh_token=refresh_token,
                    expires_at=expires_at,
                )
            )
        else:
            existing.access_token = access_token
            existing.refresh_token = refresh_token
            existing.expires_at = expires_at
        self._session.flush()

    def exchange_and_store(self, *, company_id: uuid.UUID, code: str) -> None:
        """Exchange an authorization code for a token and store it."""
        token = self._client.exchange_code(code=code)
        self.store_token(
            company_id=company_id,
            access_token=token.access_token,
            refresh_token=token.refresh_token,
            expires_in=token.expires_in,
        )

    def is_connected(self, company_id: uuid.UUID) -> bool:
        return (
            self._session.scalar(
                select(HmrcToken).where(HmrcToken.company_id == company_id)
            )
            is not None
        )

    def _access_token(self, company_id: uuid.UUID) -> str:
        token = self._session.scalar(
            select(HmrcToken).where(HmrcToken.company_id == company_id)
        )
        if token is None:
            raise MtdNotConnectedError("HMRC account is not connected")
        return token.access_token

    # -- obligations + submission ----------------------------------------

    def obligations(
        self, company_id: uuid.UUID, *, from_date: str, to_date: str
    ) -> list[VatObligation]:
        vrn = self._vrn(company_id)
        token = self._access_token(company_id)
        try:
            return self._client.list_obligations(
                access_token=token, vrn=vrn, from_date=from_date, to_date=to_date
            )
        except HmrcError as exc:
            raise MtdError(str(exc)) from exc

    def submit_to_hmrc(
        self,
        *,
        actor_id: uuid.UUID,
        company_id: uuid.UUID,
        submission_id: uuid.UUID,
        period_key: str,
    ) -> SubmitResult:
        """Submit a finalised VAT return to HMRC and store the receipt."""
        submission = self._session.get(VatReturnSubmission, submission_id)
        if submission is None or submission.company_id != company_id:
            raise SubmissionNotFoundError
        if submission.hmrc_status == "submitted":
            raise AlreadySubmittedError("This return is already filed with HMRC")

        vrn = self._vrn(company_id)
        token = self._access_token(company_id)
        ret = NineBoxReturn(
            period_key=period_key,
            box1_minor=submission.box1_minor,
            box2_minor=submission.box2_minor,
            box3_minor=submission.box3_minor,
            box4_minor=submission.box4_minor,
            box5_minor=submission.box5_minor,
            box6_minor=submission.box6_minor,
            box7_minor=submission.box7_minor,
            box8_minor=submission.box8_minor,
            box9_minor=submission.box9_minor,
        )
        try:
            receipt = self._client.submit_return(access_token=token, vrn=vrn, ret=ret)
        except HmrcError as exc:
            submission.hmrc_status = "error"
            self._session.flush()
            raise MtdError(str(exc)) from exc

        received_at = utcnow()
        submission.hmrc_status = "submitted"
        submission.hmrc_period_key = period_key
        submission.hmrc_form_bundle = receipt.form_bundle_number
        submission.hmrc_charge_ref = receipt.charge_ref_number
        submission.hmrc_receipt_at = received_at
        self._session.flush()
        record_audit(
            self._session,
            entity_type="vat_return_submission",
            entity_id=submission.id,
            action="hmrc_submitted",
            actor_user_id=actor_id,
            company_id=company_id,
        )
        return SubmitResult(
            submission_id=submission.id,
            form_bundle_number=receipt.form_bundle_number,
            charge_ref_number=receipt.charge_ref_number,
            received_at=received_at,
        )
