"""Reversals.

The ledger is append-only, so a mistake is corrected by posting the mirror image of
the original entry, linked back to it through ``reverses_id``.  The correct entry is
then posted separately.  Nothing is ever edited or deleted.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import Conflict, NotFound
from app.ledger.posting import LineDraft, post
from app.models import JournalEntry, LedgerEvent


def reverse_entry(
    db: Session,
    entry_id: int,
    *,
    reason: str,
    created_by: str,
    on: date | None = None,
    bypass_period_lock: bool = False,
) -> JournalEntry:
    """Post the mirror image of *entry_id*."""
    original = db.get(JournalEntry, entry_id)
    if original is None:
        raise NotFound(f"unknown journal entry {entry_id}", entry_id=entry_id)

    existing = db.execute(
        select(JournalEntry.id).where(JournalEntry.reverses_id == entry_id)
    ).scalar_one_or_none()
    if existing is not None:
        raise Conflict(
            f"entry {entry_id} was already reversed by entry {existing}",
            entry_id=entry_id,
            reversed_by=existing,
        )

    lines = [
        LineDraft(
            account_code=line.account_code,
            amount=-line.amount,
            client_id=line.client_id,
            holding_id=line.holding_id,
            currency=line.currency,
            fx_rate=line.fx_rate,
            base_amount=-line.base_amount,
            description=f"Reversal: {line.description}" if line.description else "Reversal",
        )
        for line in original.lines
    ]

    return post(
        db,
        entry_date=on or original.entry_date,
        event=LedgerEvent.REVERSAL,
        client_id=original.client_id,
        currency=original.currency,
        lines=lines,
        narrative=f"Reversal of entry {entry_id}: {reason}",
        reference=original.reference,
        instruction_id=original.instruction_id,
        reverses_id=entry_id,
        batch_id=original.batch_id,
        created_by=created_by,
        multi_currency=len({line.currency for line in original.lines}) > 1,
        bypass_period_lock=bypass_period_lock,
    )
