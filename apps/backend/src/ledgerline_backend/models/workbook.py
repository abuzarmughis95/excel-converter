"""Spreadsheet workbook models.

A workbook belongs to a company and holds one or more named sheets. Each sheet
stores its grid as JSON (a list of rows, each a list of string cells). This backs
the spreadsheet screen where users enter free-form tabular data across multiple
sheets and save the whole workbook (Ctrl+S) to the backend so it syncs across
devices.

The grid is stored as opaque JSON here; mapping cells to VAT boxes / accounting
data is a later concern (the MTD bridge, Phase 5).
"""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ledgerline_backend.db.base import AuditableBase


class Workbook(AuditableBase):
    """A company's spreadsheet workbook (a collection of sheets)."""

    __tablename__ = "workbooks"
    __table_args__ = (
        # One workbook per company for now (the default working set).
        UniqueConstraint("company_id", "name", name="uq_workbook_company_name"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="Workbook")


class Sheet(AuditableBase):
    """A single named sheet (tab) within a workbook, with its cell grid."""

    __tablename__ = "sheets"
    __table_args__ = (
        UniqueConstraint("workbook_id", "name", name="uq_sheet_workbook_name"),
    )

    workbook_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workbooks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Grid stored as JSON: list[list[str]] (rows of string cells).
    cells: Mapped[list[list[str]]] = mapped_column(JSON, nullable=False, default=list)
