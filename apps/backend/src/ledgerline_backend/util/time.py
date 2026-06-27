"""Time helpers shared across the backend."""

from __future__ import annotations

import datetime as dt


def utcnow() -> dt.datetime:
    """The current time as a timezone-aware UTC datetime.

    Centralised so every caller uses an aware UTC value (naive datetimes cause
    subtle comparison bugs against DB-stored timestamps).
    """
    return dt.datetime.now(tz=dt.UTC)
