"""Shared company-membership RBAC dependencies.

Routers annotate an endpoint parameter with one of these to require a minimum
company role. Centralised so every router enforces the same role thresholds and
the wiring lives in one place.

Role ladder: readonly < bookkeeper < accountant < owner. ``require_company_role``
returns 404 for a non-member (leak-safe) and 403 for an insufficient role.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from ledgerline_backend.models import CompanyMembership
from ledgerline_backend.models.membership import (
    ROLE_ACCOUNTANT,
    ROLE_BOOKKEEPER,
    ROLE_OWNER,
    ROLE_READONLY,
)
from ledgerline_backend.security.rbac import require_company_role

# Read = any member of the company.
ReadMembership = Annotated[
    CompanyMembership, Depends(require_company_role(ROLE_READONLY))
]
# Write = bookkeeper or above (post journals, import statements, etc.).
WriteMembership = Annotated[
    CompanyMembership, Depends(require_company_role(ROLE_BOOKKEEPER))
]
# Manage = accountant or above (lock periods, finalise VAT, etc.).
AccountantMembership = Annotated[
    CompanyMembership, Depends(require_company_role(ROLE_ACCOUNTANT))
]
# Owner-only (manage members, delete the company, etc.).
OwnerMembership = Annotated[
    CompanyMembership, Depends(require_company_role(ROLE_OWNER))
]
