"""Fixed-asset register service.

Creates assets, lists the register with net book value, and runs depreciation for
a period — which computes the charge via the engine and posts a balanced journal
(Dr depreciation expense, Cr accumulated depreciation) through the posting
service, then advances the asset's accumulated state. Running again once an asset
is fully depreciated is a no-op.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from decimal import Decimal

from ledgerline_engine.api import (
    DepreciationMethod,
    FixedAssetSpec,
    period_charge,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from ledgerline_backend.models import ChartOfAccount, FixedAsset
from ledgerline_backend.services.audit import record_audit
from ledgerline_backend.services.posting_service import LineInput, PostingService


class AssetError(Exception):
    """Base class for fixed-asset failures."""


class AssetNotFoundError(AssetError):
    """No such asset in the company."""


class InvalidAssetError(AssetError):
    """The asset's parameters are invalid."""


class GLAccountInvalidError(AssetError):
    """A referenced GL account is missing or in the wrong company."""


@dataclass(frozen=True)
class AssetView:
    id: uuid.UUID
    name: str
    category: str | None
    acquired_on: dt.date
    cost_minor: int
    residual_minor: int
    method: str
    useful_life_periods: int | None
    rate_percent: float | None
    accumulated_depreciation_minor: int
    net_book_value_minor: int
    periods_depreciated: int
    disposed: bool


@dataclass(frozen=True)
class DepreciationRunResult:
    asset_id: uuid.UUID
    charge_minor: int
    journal_id: uuid.UUID | None  # None when there was nothing to depreciate


class AssetService:
    """Fixed-asset register operations for a company."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def _get(self, company_id: uuid.UUID, asset_id: uuid.UUID) -> FixedAsset:
        asset = self._session.get(FixedAsset, asset_id)
        if asset is None or asset.company_id != company_id:
            raise AssetNotFoundError
        return asset

    def _spec(self, asset: FixedAsset) -> FixedAssetSpec:
        return FixedAssetSpec(
            cost_minor=asset.cost_minor,
            residual_minor=asset.residual_minor,
            method=DepreciationMethod(asset.method),
            useful_life_periods=asset.useful_life_periods,
            rate_percent=(
                Decimal(str(asset.rate_percent)) if asset.rate_percent is not None else None
            ),
        )

    def _view(self, asset: FixedAsset) -> AssetView:
        return AssetView(
            id=asset.id,
            name=asset.name,
            category=asset.category,
            acquired_on=asset.acquired_on,
            cost_minor=asset.cost_minor,
            residual_minor=asset.residual_minor,
            method=asset.method,
            useful_life_periods=asset.useful_life_periods,
            rate_percent=float(asset.rate_percent) if asset.rate_percent is not None else None,
            accumulated_depreciation_minor=asset.accumulated_depreciation_minor,
            net_book_value_minor=asset.cost_minor - asset.accumulated_depreciation_minor,
            periods_depreciated=asset.periods_depreciated,
            disposed=asset.disposed,
        )

    def _require_account(self, company_id: uuid.UUID, account_id: uuid.UUID) -> ChartOfAccount:
        account = self._session.get(ChartOfAccount, account_id)
        if account is None or account.company_id != company_id or not account.is_active:
            raise GLAccountInvalidError("GL account is invalid for this company")
        return account

    def list_assets(self, company_id: uuid.UUID) -> list[AssetView]:
        rows = self._session.scalars(
            select(FixedAsset)
            .where(FixedAsset.company_id == company_id)
            .order_by(FixedAsset.acquired_on, FixedAsset.name)
        ).all()
        return [self._view(a) for a in rows]

    def create(
        self,
        *,
        actor_id: uuid.UUID,
        company_id: uuid.UUID,
        name: str,
        acquired_on: dt.date,
        cost_minor: int,
        method: str,
        asset_account_id: uuid.UUID,
        accumulated_account_id: uuid.UUID,
        expense_account_id: uuid.UUID,
        residual_minor: int = 0,
        useful_life_periods: int | None = None,
        rate_percent: float | None = None,
        category: str | None = None,
    ) -> AssetView:
        if not name.strip():
            raise InvalidAssetError("Asset name is required")
        # Validate the engine spec (raises DepreciationError -> InvalidAssetError).
        from ledgerline_engine.api import DepreciationError

        try:
            FixedAssetSpec(
                cost_minor=cost_minor,
                residual_minor=residual_minor,
                method=DepreciationMethod(method),
                useful_life_periods=useful_life_periods,
                rate_percent=Decimal(str(rate_percent)) if rate_percent is not None else None,
            )
        except (DepreciationError, ValueError) as exc:
            raise InvalidAssetError(str(exc)) from exc

        for account_id in (asset_account_id, accumulated_account_id, expense_account_id):
            self._require_account(company_id, account_id)

        asset = FixedAsset(
            company_id=company_id,
            name=name.strip(),
            category=category,
            acquired_on=acquired_on,
            cost_minor=cost_minor,
            residual_minor=residual_minor,
            method=method,
            useful_life_periods=useful_life_periods,
            rate_percent=rate_percent,
            asset_account_id=asset_account_id,
            accumulated_account_id=accumulated_account_id,
            expense_account_id=expense_account_id,
        )
        self._session.add(asset)
        self._session.flush()
        record_audit(
            self._session,
            entity_type="fixed_asset",
            entity_id=asset.id,
            action="asset_created",
            actor_user_id=actor_id,
            company_id=company_id,
        )
        return self._view(asset)

    def run_depreciation(
        self,
        *,
        actor_id: uuid.UUID,
        company_id: uuid.UUID,
        asset_id: uuid.UUID,
        on_date: dt.date,
    ) -> DepreciationRunResult:
        """Depreciate the asset by one period, posting a journal for the charge."""
        asset = self._get(company_id, asset_id)
        if asset.disposed:
            raise InvalidAssetError("Asset is disposed")

        charge = period_charge(
            self._spec(asset),
            accumulated_minor=asset.accumulated_depreciation_minor,
            period_index=asset.periods_depreciated + 1,
        )
        if charge == 0:
            return DepreciationRunResult(asset_id=asset.id, charge_minor=0, journal_id=None)

        # Dr depreciation expense, Cr accumulated depreciation.
        view = PostingService(self._session).create(
            actor_id=actor_id,
            company_id=company_id,
            journal_date=on_date,
            journal_type="depreciation",
            narrative=f"Depreciation: {asset.name}",
            lines=[
                LineInput(account_id=asset.expense_account_id, debit_minor=charge),
                LineInput(account_id=asset.accumulated_account_id, credit_minor=charge),
            ],
        )
        PostingService(self._session).post(
            actor_id=actor_id, company_id=company_id, journal_id=view.id
        )

        asset.accumulated_depreciation_minor += charge
        asset.periods_depreciated += 1
        self._session.flush()
        record_audit(
            self._session,
            entity_type="fixed_asset",
            entity_id=asset.id,
            action="asset_depreciated",
            actor_user_id=actor_id,
            company_id=company_id,
        )
        return DepreciationRunResult(asset_id=asset.id, charge_minor=charge, journal_id=view.id)
