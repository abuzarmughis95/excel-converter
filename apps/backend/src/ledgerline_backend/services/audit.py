"""Audit trail writer.

Records an immutable audit entry for every significant mutation. Each entry is
linked to the previous entry (globally, for now) via a SHA-256 hash chain so
tampering is detectable: altering or deleting a past entry breaks the chain.

NOTE: this is a foundational writer. The full per-aggregate chaining and the
trigger-enforced immutability are completed in AC-10 (Phase 2); here we provide a
correct, chained writer that the company/device/auth services use today.
"""

from __future__ import annotations

import hashlib
import uuid

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ledgerline_backend.models import AllocationCounter, AuditLog
from ledgerline_backend.models.allocation import AUDIT_SEQ_COUNTER


def _next_audit_seq(session: Session) -> int:
    """Allocate the next monotonic audit sequence number, race-safely.

    Locks the counter row (``FOR UPDATE`` on PostgreSQL) before incrementing so
    concurrent writers cannot collide. Mirrors the node-id allocator.
    """
    dialect = session.get_bind().dialect.name
    counter = session.get(
        AllocationCounter,
        AUDIT_SEQ_COUNTER,
        with_for_update=dialect == "postgresql",
    )
    if counter is None:
        counter = AllocationCounter(name=AUDIT_SEQ_COUNTER, value=0)
        session.add(counter)
        session.flush()
    counter.value += 1
    session.flush()
    return counter.value


def _canonical(
    *,
    prev_hash: bytes | None,
    entity_type: str,
    entity_id: uuid.UUID,
    action: str,
    actor_user_id: uuid.UUID | None,
    company_id: uuid.UUID | None,
    reason: str | None,
) -> bytes:
    """Deterministic byte representation hashed into the chain."""
    parts = [
        prev_hash.hex() if prev_hash is not None else "",
        entity_type,
        str(entity_id),
        action,
        str(actor_user_id) if actor_user_id is not None else "",
        str(company_id) if company_id is not None else "",
        reason or "",
    ]
    return "\x1f".join(parts).encode("utf-8")


def record_audit(
    session: Session,
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    action: str,
    actor_user_id: uuid.UUID | None = None,
    company_id: uuid.UUID | None = None,
    reason: str | None = None,
) -> AuditLog:
    """Append a tamper-evident audit entry and return it.

    The chain is PER-AGGREGATE: the new entry's ``prev_hash`` is the previous
    entry's ``this_hash`` for the same (entity_type, entity_id), giving each
    entity its own verifiable history. ``this_hash`` covers the previous hash
    plus this entry's fields.

    NOTE: append-only immutability is enforced at the application layer here;
    database-trigger enforcement is completed in AC-10 (Phase 2).
    """
    head = session.scalar(
        select(AuditLog)
        .where(AuditLog.entity_type == entity_type, AuditLog.entity_id == entity_id)
        .order_by(desc(AuditLog.seq))
        .limit(1)
    )
    prev_hash = head.this_hash if head is not None else None

    payload = _canonical(
        prev_hash=prev_hash,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor_user_id=actor_user_id,
        company_id=company_id,
        reason=reason,
    )
    this_hash = hashlib.sha256((prev_hash or b"") + payload).digest()

    entry = AuditLog(
        seq=_next_audit_seq(session),
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor_user_id=actor_user_id,
        company_id=company_id,
        reason=reason,
        prev_hash=prev_hash,
        this_hash=this_hash,
    )
    session.add(entry)
    session.flush()
    return entry
