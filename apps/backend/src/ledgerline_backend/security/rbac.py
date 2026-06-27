"""Reusable RBAC dependencies for company-scoped routes.

Rather than each handler re-deriving the caller's membership and checking their
role, routes declare the minimum role they need via ``require_company_role``.
The dependency resolves the membership for the ``company_id`` path parameter,
enforces the role, and returns the membership so the handler has the role for
free. Non-members get a leak-safe 404; insufficient role gets 403.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import HTTPException, Path, status
from sqlalchemy import select

from ledgerline_backend.dependencies import CurrentUserDep, SessionDep
from ledgerline_backend.models import CompanyMembership
from ledgerline_backend.models.membership import role_at_least


def require_company_role(
    min_role: str,
) -> Callable[..., CompanyMembership]:
    """Build a dependency enforcing ``min_role`` on the path's company_id.

    Usage::

        Dep = Annotated[CompanyMembership, Depends(require_company_role("accountant"))]

        @router.get("/companies/{company_id}/...")
        def handler(membership: Dep): ...
    """

    def dependency(
        company_id: Annotated[uuid.UUID, Path()],
        current_user: CurrentUserDep,
        session: SessionDep,
    ) -> CompanyMembership:
        membership = session.scalar(
            select(CompanyMembership).where(
                CompanyMembership.user_id == current_user.id,
                CompanyMembership.company_id == company_id,
            )
        )
        # Non-membership is reported as not-found to avoid leaking which
        # companies exist.
        if membership is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Company not found"
            )
        if not role_at_least(membership.role, min_role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your role does not permit this action",
            )
        return membership

    return dependency
