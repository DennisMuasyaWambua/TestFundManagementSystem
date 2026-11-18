"""Fair valuation of Sukuk and investment property, maker-checker.

Cost is never overwritten.  A valuation posts the difference to a fair value
adjustment account so that cost + adjustment = fair value, which keeps the original
cost visible for ever and makes the gain or loss explicit in the P&L.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import BusinessRule, Conflict, MakerCheckerBreach, NotFound
from app.ledger.posting import PostingContext, build_lines, post
from app.ledger.rules import event_for
from app.models import (
    ApprovalStatus,
    AssetClass,
    Client,
    Holding,
    JournalEntry,
    LedgerEvent,
    Valuation,
    utcnow,
)
from app.money import ZERO, money, round_money
from app.services import audit
from app.services import holdings as holdings_svc

FAIR_VALUED = (AssetClass.SUKUK, AssetClass.PROPERTY)


def value_from_price(holding: Holding, price: Decimal) -> Decimal:
    """A Sukuk price is quoted per 100 of nominal."""
    if holding.nominal is None:
        raise BusinessRule(
            f"holding {holding.id} has no nominal, so a price per 100 cannot be applied",
            holding_id=holding.id,
        )
    return round_money(holding.nominal * price / Decimal(100))


def propose(
    db: Session,
    *,
    holding_id: str,
    valuation_date: date,
    source: str,
    prepared_by: str,
    price: Decimal | None = None,
    value: Decimal | None = None,
    valuer_name: str | None = None,
    report_ref: str | None = None,
    report_file_id: int | None = None,
) -> Valuation:
    holding = holdings_svc.get_holding(db, holding_id)
    if holding.asset_class not in FAIR_VALUED:
        raise BusinessRule(
            f"{holding.asset_class} holdings are not carried at fair value",
            holding_id=holding_id,
            asset_class=str(holding.asset_class),
        )
    if price is None and value is None:
        raise BusinessRule("a valuation needs either a price per 100 nominal or a value")
    if holding.asset_class is AssetClass.PROPERTY and not (valuer_name and report_ref):
        raise BusinessRule(
            "a property valuation needs the valuer's name and the report reference",
            holding_id=holding_id,
        )

    resolved = value if value is not None else value_from_price(holding, price or ZERO)
    if resolved < 0:
        raise BusinessRule("a fair value cannot be negative", value=str(resolved))

    pending = db.execute(
        select(Valuation).where(
            Valuation.holding_id == holding_id,
            Valuation.valuation_date == valuation_date,
            Valuation.status == ApprovalStatus.PENDING,
        )
    ).scalar_one_or_none()
    if pending is not None:
        raise Conflict(
            f"a valuation of {holding_id} at {valuation_date.isoformat()} is already awaiting "
            "approval",
            valuation_id=pending.id,
        )

    valuation = Valuation(
        holding_id=holding_id,
        client_id=holding.client_id,
        valuation_date=valuation_date,
        price=price,
        value=money(resolved),
        source=source,
        valuer_name=valuer_name,
        report_ref=report_ref,
        report_file_id=report_file_id,
        status=ApprovalStatus.PENDING,
        prepared_by=prepared_by,
        created_by=prepared_by,
    )
    db.add(valuation)
    db.flush()
    audit.record(
        db,
        user_id=prepared_by,
        action="VALUATION_PROPOSED",
        entity="valuation",
        entity_id=valuation.id,
        client_id=holding.client_id,
        detail={
            "holding_id": holding_id,
            "valuation_date": valuation_date.isoformat(),
            "value": f"{valuation.value:.2f}",
            "source": source,
        },
    )
    return valuation


def revalue_to(
    db: Session,
    holding: Holding,
    *,
    on: date,
    target: Decimal,
    created_by: str,
    narrative: str,
    bypass_period_lock: bool = False,
) -> JournalEntry | None:
    """Post the difference so that cost + adjustment equals *target*."""
    cost = holdings_svc.outstanding(db, holding, on)
    adjustment = holdings_svc.fair_value_adjustment(db, holding, on)
    delta = money(target - cost - adjustment)
    if delta == 0:
        return None

    client = db.get(Client, holding.client_id)
    assert client is not None
    ctx = PostingContext(
        client=client,
        custody_account=holdings_svc.custody_account_for(db, holding),
        holding=holding,
        descriptions={"amount": narrative},
    )
    rule_key = "FAIR_VALUE_GAIN" if delta > 0 else "FAIR_VALUE_LOSS"
    lines = build_lines(db, ctx, rule_key, {"amount": abs(delta)})
    return post(
        db,
        entry_date=on,
        event=event_for(rule_key),
        client_id=holding.client_id,
        currency=holding.currency,
        lines=lines,
        narrative=narrative,
        created_by=created_by,
        bypass_period_lock=bypass_period_lock,
    )


def approve(db: Session, valuation_id: int, *, approver_id: str) -> Valuation:
    valuation = db.get(Valuation, valuation_id)
    if valuation is None:
        raise NotFound(f"unknown valuation {valuation_id}", valuation_id=valuation_id)
    if valuation.status is not ApprovalStatus.PENDING:
        raise Conflict(
            f"valuation {valuation_id} is already {valuation.status}",
            status=str(valuation.status),
        )
    if valuation.prepared_by == approver_id:
        raise MakerCheckerBreach(
            "the person who proposed a valuation cannot approve it",
            valuation_id=valuation_id,
        )

    holding = holdings_svc.get_holding(db, valuation.holding_id)
    entry = revalue_to(
        db,
        holding,
        on=valuation.valuation_date,
        target=valuation.value,
        created_by=approver_id,
        narrative=(
            f"Fair value of {holding.id} at {valuation.valuation_date.isoformat()}: "
            f"{valuation.source}"
        ),
    )
    valuation.status = ApprovalStatus.APPROVED
    valuation.approved_by = approver_id
    valuation.approved_at = utcnow()
    valuation.journal_entry_id = entry.id if entry is not None else None
    db.flush()
    audit.record(
        db,
        user_id=approver_id,
        action="VALUATION_APPROVED",
        entity="valuation",
        entity_id=valuation.id,
        client_id=valuation.client_id,
        detail={
            "holding_id": valuation.holding_id,
            "value": f"{valuation.value:.2f}",
            "journal_entry_id": valuation.journal_entry_id,
        },
    )
    return valuation


def reject(db: Session, valuation_id: int, *, approver_id: str, reason: str) -> Valuation:
    valuation = db.get(Valuation, valuation_id)
    if valuation is None:
        raise NotFound(f"unknown valuation {valuation_id}", valuation_id=valuation_id)
    if valuation.status is not ApprovalStatus.PENDING:
        raise Conflict(
            f"valuation {valuation_id} is already {valuation.status}",
            status=str(valuation.status),
        )
    if valuation.prepared_by == approver_id:
        raise MakerCheckerBreach(
            "the person who proposed a valuation cannot reject it",
            valuation_id=valuation_id,
        )
    if not reason.strip():
        raise BusinessRule("a rejection needs a reason")
    valuation.status = ApprovalStatus.REJECTED
    valuation.approved_by = approver_id
    valuation.approved_at = utcnow()
    valuation.rejection_reason = reason
    db.flush()
    audit.record(
        db,
        user_id=approver_id,
        action="VALUATION_REJECTED",
        entity="valuation",
        entity_id=valuation.id,
        client_id=valuation.client_id,
        detail={"reason": reason},
    )
    return valuation


def pending_for_client(db: Session, client_id: str) -> list[Valuation]:
    return list(
        db.execute(
            select(Valuation)
            .where(Valuation.client_id == client_id, Valuation.status == ApprovalStatus.PENDING)
            .order_by(Valuation.valuation_date)
        ).scalars()
    )


def history(db: Session, holding_id: str) -> list[Valuation]:
    return list(
        db.execute(
            select(Valuation)
            .where(Valuation.holding_id == holding_id)
            .order_by(Valuation.valuation_date.desc(), Valuation.id.desc())
        ).scalars()
    )


__all__ = [
    "FAIR_VALUED",
    "LedgerEvent",
    "approve",
    "history",
    "pending_for_client",
    "propose",
    "reject",
    "revalue_to",
    "value_from_price",
]
