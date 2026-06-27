"""Workbook service — load/save a company's multi-sheet spreadsheet.

Provides get-or-create for the company's default workbook and a full save that
replaces the set of sheets with the submitted ones. Saving is what Ctrl+S in the
UI calls; the whole workbook is persisted so it syncs across devices.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ledgerline_backend.models import Sheet, Workbook
from ledgerline_backend.services.audit import record_audit

# Guardrails so a single workbook cannot grow unbounded.
MAX_SHEETS = 50
MAX_ROWS = 1000
MAX_COLS = 100

DEFAULT_WORKBOOK_NAME = "Workbook"


class WorkbookError(Exception):
    """Base class for workbook failures."""


class WorkbookTooLargeError(WorkbookError):
    """The submitted workbook exceeds the allowed size limits."""


@dataclass(frozen=True)
class SheetInput:
    """A sheet to save: a name and its grid of string cells."""

    name: str
    cells: list[list[str]] = field(default_factory=list)


@dataclass(frozen=True)
class SheetView:
    name: str
    sort_order: int
    cells: list[list[str]]


@dataclass(frozen=True)
class WorkbookView:
    id: uuid.UUID
    name: str
    sheets: list[SheetView]


class WorkbookService:
    """Load and save a company's spreadsheet workbook."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def _get_or_create(self, company_id: uuid.UUID) -> Workbook:
        workbook = self._session.scalar(
            select(Workbook).where(
                Workbook.company_id == company_id,
                Workbook.name == DEFAULT_WORKBOOK_NAME,
            )
        )
        if workbook is None:
            workbook = Workbook(company_id=company_id, name=DEFAULT_WORKBOOK_NAME)
            self._session.add(workbook)
            self._session.flush()
            # Seed with one empty sheet so the UI always has a tab.
            self._session.add(
                Sheet(workbook_id=workbook.id, name="Sheet1", sort_order=0, cells=[])
            )
            self._session.flush()
        return workbook

    def _sheets(self, workbook_id: uuid.UUID) -> list[Sheet]:
        return list(
            self._session.scalars(
                select(Sheet)
                .where(Sheet.workbook_id == workbook_id)
                .order_by(Sheet.sort_order)
            ).all()
        )

    def load(self, company_id: uuid.UUID) -> WorkbookView:
        """Load the company's workbook (creating a default one if needed)."""
        workbook = self._get_or_create(company_id)
        sheets = self._sheets(workbook.id)
        return WorkbookView(
            id=workbook.id,
            name=workbook.name,
            sheets=[
                SheetView(name=s.name, sort_order=s.sort_order, cells=s.cells) for s in sheets
            ],
        )

    def save(
        self, *, actor_id: uuid.UUID, company_id: uuid.UUID, sheets: list[SheetInput]
    ) -> WorkbookView:
        """Replace the workbook's sheets with the submitted set (Ctrl+S)."""
        if len(sheets) > MAX_SHEETS:
            raise WorkbookTooLargeError(f"At most {MAX_SHEETS} sheets are allowed")
        seen: set[str] = set()
        for s in sheets:
            if not s.name.strip():
                raise WorkbookError("Sheet names must not be empty")
            if s.name in seen:
                raise WorkbookError(f"Duplicate sheet name: {s.name}")
            seen.add(s.name)
            if len(s.cells) > MAX_ROWS:
                raise WorkbookTooLargeError(f"A sheet may have at most {MAX_ROWS} rows")
            for row in s.cells:
                if len(row) > MAX_COLS:
                    raise WorkbookTooLargeError(f"A sheet may have at most {MAX_COLS} columns")

        workbook = self._get_or_create(company_id)
        # Replace all existing sheets with the submitted set.
        for existing in self._sheets(workbook.id):
            self._session.delete(existing)
        self._session.flush()
        for order, s in enumerate(sheets):
            self._session.add(
                Sheet(
                    workbook_id=workbook.id,
                    name=s.name.strip(),
                    sort_order=order,
                    cells=s.cells,
                )
            )
        workbook.version += 1
        self._session.flush()
        record_audit(
            self._session,
            entity_type="workbook",
            entity_id=workbook.id,
            action="saved",
            actor_user_id=actor_id,
            company_id=company_id,
            reason=f"sheets={len(sheets)}",
        )
        return self.load(company_id)
