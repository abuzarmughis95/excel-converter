"""Workbook (spreadsheet) endpoints — load and save a company's sheets.

Company-scoped, RBAC-enforced (read = any member, write = bookkeeper+). The save
endpoint is what the desktop app's Ctrl+S calls; it persists the whole workbook.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from ledgerline_backend.api.membership_deps import ReadMembership, WriteMembership
from ledgerline_backend.dependencies import CurrentUserDep, SessionDep
from ledgerline_backend.services.workbook_service import (
    MAX_COLS,
    MAX_ROWS,
    MAX_SHEETS,
    SheetInput,
    WorkbookError,
    WorkbookService,
    WorkbookTooLargeError,
    WorkbookView,
)

router = APIRouter(prefix="/companies/{company_id}/workbook", tags=["workbook"])



class SheetModel(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    cells: list[list[str]] = Field(default_factory=list)


class SaveWorkbookRequest(BaseModel):
    sheets: list[SheetModel] = Field(min_length=1, max_length=MAX_SHEETS)


class SheetResponse(BaseModel):
    name: str
    sort_order: int
    cells: list[list[str]]


class WorkbookResponse(BaseModel):
    id: uuid.UUID
    name: str
    sheets: list[SheetResponse]


def _to_response(v: WorkbookView) -> WorkbookResponse:
    return WorkbookResponse(
        id=v.id,
        name=v.name,
        sheets=[
            SheetResponse(name=s.name, sort_order=s.sort_order, cells=s.cells) for s in v.sheets
        ],
    )


@router.get("", response_model=WorkbookResponse)
def load_workbook(
    company_id: uuid.UUID,
    membership: ReadMembership,
    session: SessionDep,
) -> WorkbookResponse:
    """Load the company's workbook (creates a default one on first access)."""
    return _to_response(WorkbookService(session).load(company_id))


@router.put("", response_model=WorkbookResponse)
def save_workbook(
    company_id: uuid.UUID,
    body: SaveWorkbookRequest,
    current_user: CurrentUserDep,
    membership: WriteMembership,
    session: SessionDep,
) -> WorkbookResponse:
    """Save the whole workbook (Ctrl+S). Replaces the existing sheets."""
    try:
        workbook = WorkbookService(session).save(
            actor_id=current_user.id,
            company_id=company_id,
            sheets=[SheetInput(name=s.name, cells=s.cells) for s in body.sheets],
        )
    except WorkbookTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Workbook too large (max {MAX_SHEETS} sheets, {MAX_ROWS}x{MAX_COLS} cells)",
        ) from exc
    except WorkbookError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return _to_response(workbook)
