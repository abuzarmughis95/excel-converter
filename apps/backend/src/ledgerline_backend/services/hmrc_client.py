"""HMRC Making Tax Digital (MTD) for VAT client.

Wraps the HMRC VAT (MTD) API: the OAuth2 token exchange, listing VAT obligations,
and submitting a 9-box return. The HTTP work sits behind the ``HmrcClient``
Protocol so the service layer and tests can inject a fake — no live HMRC calls
happen in tests.

Real calls go to the configured base URL (sandbox by default). HMRC requires a
set of fraud-prevention headers (``Gov-Client-*`` / ``Gov-Vendor-*``); a minimal,
honest set is sent. Amounts on the wire are major-unit decimals (pounds), per the
HMRC schema, converted from our integer minor units at the edge.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

import httpx


class HmrcError(Exception):
    """An HMRC API call failed."""


class HmrcAuthError(HmrcError):
    """OAuth token exchange/refresh failed."""


@dataclass(frozen=True)
class HmrcToken:
    access_token: str
    refresh_token: str | None
    expires_in: int


@dataclass(frozen=True)
class VatObligation:
    """One VAT obligation (period) returned by HMRC."""

    period_key: str
    start: str  # ISO date
    end: str  # ISO date
    due: str  # ISO date
    status: str  # 'O' open | 'F' fulfilled
    received: str | None


@dataclass(frozen=True)
class VatSubmissionReceipt:
    """HMRC's acknowledgement of an accepted VAT return."""

    form_bundle_number: str
    charge_ref_number: str | None
    processing_date: str
    payment_indicator: str | None


@dataclass(frozen=True)
class NineBoxReturn:
    """The 9 boxes in HMRC's wire shape (minor units in; converted on submit)."""

    period_key: str
    box1_minor: int
    box2_minor: int
    box3_minor: int
    box4_minor: int
    box5_minor: int
    box6_minor: int
    box7_minor: int
    box8_minor: int
    box9_minor: int
    finalised: bool = True


def _pounds(minor: int) -> str:
    """Render minor units as a HMRC money string, e.g. -12345 -> '-123.45'."""
    return str((Decimal(minor) / Decimal(100)).quantize(Decimal("0.01")))


def _whole_pounds(minor: int) -> str:
    """Boxes 6-9 are whole pounds (no pence) in the HMRC schema."""
    return str(int(Decimal(minor) / Decimal(100)))


def vat_return_payload(ret: NineBoxReturn) -> dict[str, Any]:
    """Build the JSON body HMRC expects for POST .../returns."""
    return {
        "periodKey": ret.period_key,
        "vatDueSales": _pounds(ret.box1_minor),
        "vatDueAcquisitions": _pounds(ret.box2_minor),
        "totalVatDue": _pounds(ret.box3_minor),
        "vatReclaimedCurrPeriod": _pounds(ret.box4_minor),
        "netVatDue": _pounds(ret.box5_minor),
        "totalValueSalesExVAT": _whole_pounds(ret.box6_minor),
        "totalValuePurchasesExVAT": _whole_pounds(ret.box7_minor),
        "totalValueGoodsSuppliedExVAT": _whole_pounds(ret.box8_minor),
        "totalAcquisitionsExVAT": _whole_pounds(ret.box9_minor),
        "finalised": ret.finalised,
    }


class HmrcClient(Protocol):
    """Minimal HMRC interface (so tests can inject a fake)."""

    def exchange_code(self, *, code: str) -> HmrcToken: ...

    def list_obligations(
        self, *, access_token: str, vrn: str, from_date: str, to_date: str
    ) -> list[VatObligation]: ...

    def submit_return(
        self, *, access_token: str, vrn: str, ret: NineBoxReturn
    ) -> VatSubmissionReceipt: ...


# Vendor identifier sent in fraud-prevention + auth-test headers.
_VENDOR = "Ledgerline"


def _fraud_headers() -> dict[str, str]:
    """A minimal, honest set of HMRC fraud-prevention headers.

    A production integration must populate the full Gov-Client-* set from the
    end-user's device/connection. We send a server-originated subset and declare
    the connection method accordingly so the values are never fabricated.
    """
    return {
        "Gov-Client-Connection-Method": "WEB_APP_VIA_SERVER",
        "Gov-Vendor-Product-Name": _VENDOR,
        "Gov-Vendor-Version": "ledgerline=0.1.0",
    }


class HttpHmrcClient:
    """Real HMRC client over HTTPS. Used when credentials are configured."""

    def __init__(
        self,
        *,
        base_url: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        timeout: float = 30.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._timeout = timeout

    def authorize_url(self, *, state: str, scope: str = "read:vat write:vat") -> str:
        """The HMRC consent URL the user is redirected to (authorization code grant)."""
        from urllib.parse import urlencode

        query = urlencode(
            {
                "response_type": "code",
                "client_id": self._client_id,
                "scope": scope,
                "redirect_uri": self._redirect_uri,
                "state": state,
            }
        )
        return f"{self._base}/oauth/authorize?{query}"

    def exchange_code(self, *, code: str) -> HmrcToken:
        resp = httpx.post(
            f"{self._base}/oauth/token",
            data={
                "grant_type": "authorization_code",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "redirect_uri": self._redirect_uri,
                "code": code,
            },
            timeout=self._timeout,
        )
        if resp.status_code != httpx.codes.OK:
            raise HmrcAuthError(f"Token exchange failed ({resp.status_code})")
        body = resp.json()
        return HmrcToken(
            access_token=str(body["access_token"]),
            refresh_token=body.get("refresh_token"),
            expires_in=int(body.get("expires_in", 0)),
        )

    def _headers(self, access_token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.hmrc.1.0+json",
            **_fraud_headers(),
        }

    def list_obligations(
        self, *, access_token: str, vrn: str, from_date: str, to_date: str
    ) -> list[VatObligation]:
        resp = httpx.get(
            f"{self._base}/organisations/vat/{vrn}/obligations",
            params={"from": from_date, "to": to_date},
            headers=self._headers(access_token),
            timeout=self._timeout,
        )
        if resp.status_code != httpx.codes.OK:
            raise HmrcError(f"Obligations request failed ({resp.status_code})")
        obligations = resp.json().get("obligations", [])
        return [
            VatObligation(
                period_key=o["periodKey"],
                start=o["start"],
                end=o["end"],
                due=o["due"],
                status=o["status"],
                received=o.get("received"),
            )
            for o in obligations
        ]

    def submit_return(
        self, *, access_token: str, vrn: str, ret: NineBoxReturn
    ) -> VatSubmissionReceipt:
        resp = httpx.post(
            f"{self._base}/organisations/vat/{vrn}/returns",
            json=vat_return_payload(ret),
            headers={**self._headers(access_token), "Content-Type": "application/json"},
            timeout=self._timeout,
        )
        if resp.status_code not in (httpx.codes.OK, httpx.codes.CREATED):
            raise HmrcError(f"VAT return submission failed ({resp.status_code})")
        body = resp.json()
        return VatSubmissionReceipt(
            form_bundle_number=str(body["formBundleNumber"]),
            charge_ref_number=body.get("chargeRefNumber"),
            processing_date=str(body["processingDate"]),
            payment_indicator=body.get("paymentIndicator"),
        )
