"""Hand-written journals, under maker-checker.

A finance user proposes the lines; a *different* finance user approves them, and only
then is anything posted.  Correcting an existing entry is a reversal, which lives in
``app.ledger.reversal``; this is for entries that have no automated source at all.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import BusinessRule, Conflict, MakerCheckerBreach, NotFound
from app.ledger.posting import LineDraft, post
from app.models import ApprovalStatus, Client, JournalEntry, LedgerEvent, ManualJournal, utcnow
from app.money import ZERO, money
from app.services import audit


def propose(
    db: Session,
    *,
    client_id: str,
    entry_date: date,
    narrative: str,
    lines: list[dict[str, Any]],
    prepared_by: str,
) -> ManualJournal:
    client = db.get(Client, client_id)
    if client is None:
        raise NotFound(f"unknown client {client_id}", client_id=client_id)
    if len(lines) < 2:
        raise BusinessRule("a journal entry needs at least two lines")

    cleaned: list[dict[str, Any]] = []
    for index, raw in enumerate(lines, start=1):
        debit = money(raw.get("debit") or 0)
        credit = money(raw.get("credit") or 0)
        if debit != 0 and credit != 0:
            raise BusinessRule(f"line {index} carries both a debit and a credit")
        if debit == 0 and credit == 0:
            continue
        cleaned.append(
            {
                "account_code": str(raw["account_code"]),
                "holding_id": raw.get("holding_id") or None,
                "currency": (raw.get("currency") or client.base_currency).upper(),
                "debit": f"{debit:.2f}",
                "credit": f"{credit:.2f}",
                "description": str(raw.get("description") or ""),
            }
        )
    if len(cleaned) < 2:
        raise BusinessRule("a journal entry needs at least two lines that move an amount")

    row = ManualJournal(
        client_id=client_id,
        entry_date=entry_date,
        narrative=narrative,
        lines=cleaned,
        status=ApprovalStatus.PENDING,
        prepared_by=prepared_by,
        created_by=prepared_by,
    )
    db.add(row)
    db.flush()
    audit.record(
        db,
        user_id=prepared_by,
        action="MANUAL_JOURNAL_PROPOSED",
        entity="manual_journal",
        entity_id=row.id,
        client_id=client_id,
        detail={"entry_date": entry_date.isoformat(), "narrative": narrative, "lines": cleaned},
    )
    return row


def approve(
    db: Session, journal_id: int, *, approver_id: str
) -> tuple[ManualJournal, JournalEntry]:
    row = db.get(ManualJournal, journal_id)
    if row is None:
        raise NotFound(f"unknown manual journal {journal_id}", journal_id=journal_id)
    if row.status is not ApprovalStatus.PENDING:
        raise Conflict(f"manual journal {journal_id} is {row.status}", status=str(row.status))
    if row.prepared_by == approver_id:
        raise MakerCheckerBreach(
            "the person who prepared a manual journal cannot approve it", journal_id=journal_id
        )

    client = db.get(Client, row.client_id)
    assert client is not None
    currencies = {str(line["currency"]) for line in row.lines}
    drafts = [
        LineDraft(
            account_code=str(line["account_code"]),
            amount=money(Decimal(str(line["debit"])) - Decimal(str(line["credit"]))),
            client_id=row.client_id,
            holding_id=line.get("holding_id"),
            currency=str(line["currency"]),
            description=str(line.get("description") or ""),
        )
        for line in row.lines
    ]
    entry = post(
        db,
        entry_date=row.entry_date,
        event=LedgerEvent.MANUAL,
        client_id=row.client_id,
        currency=client.base_currency if len(currencies) > 1 else next(iter(currencies)),
        lines=drafts,
        narrative=row.narrative,
        created_by=approver_id,
        multi_currency=len(currencies) > 1,
    )
    row.status = ApprovalStatus.APPROVED
    row.approved_by = approver_id
    row.approved_at = utcnow()
    row.journal_entry_id = entry.id
    db.flush()
    audit.record(
        db,
        user_id=approver_id,
        action="MANUAL_JOURNAL_APPROVED",
        entity="manual_journal",
        entity_id=row.id,
        client_id=row.client_id,
        detail={"journal_entry_id": entry.id},
    )
    return row, entry


def reject(db: Session, journal_id: int, *, approver_id: str, reason: str) -> ManualJournal:
    row = db.get(ManualJournal, journal_id)
    if row is None:
        raise NotFound(f"unknown manual journal {journal_id}", journal_id=journal_id)
    if row.status is not ApprovalStatus.PENDING:
        raise Conflict(f"manual journal {journal_id} is {row.status}", status=str(row.status))
    if row.prepared_by == approver_id:
        raise MakerCheckerBreach("the preparer cannot reject their own manual journal")
    if not reason.strip():
        raise BusinessRule("a rejection needs a reason")
    row.status = ApprovalStatus.REJECTED
    row.approved_by = approver_id
    row.approved_at = utcnow()
    row.rejection_reason = reason
    db.flush()
    audit.record(
        db,
        user_id=approver_id,
        action="MANUAL_JOURNAL_REJECTED",
        entity="manual_journal",
        entity_id=row.id,
        client_id=row.client_id,
        detail={"reason": reason},
    )
    return row


def pending(db: Session, *, client_id: str | None = None) -> list[ManualJournal]:
    stmt = (
        select(ManualJournal)
        .where(ManualJournal.status == ApprovalStatus.PENDING)
        .order_by(ManualJournal.id.desc())
    )
    if client_id:
        stmt = stmt.where(ManualJournal.client_id == client_id)
    return list(db.execute(stmt).scalars())


__all__ = ["ZERO", "approve", "pending", "propose", "reject"]
