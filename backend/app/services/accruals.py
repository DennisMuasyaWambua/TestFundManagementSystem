"""Daily accrual of profit, monthly rent invoicing and the management fee.

Every function here is idempotent: it computes the cumulative target and posts only
the difference, so a job can be re-run -- or run twice on the same day -- without
double-posting.  Rent invoicing is made idempotent by a unique entry reference.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ledger.posting import PostingContext, build_lines, post
from app.ledger.rules import event_for
from app.models import AssetClass, Client, Holding, HoldingStatus, JournalEntry, LedgerEvent
from app.money import ZERO, money, round_money
from app.services import holdings as holdings_svc

RENT_PREFIX = "RENT"


@dataclass(frozen=True)
class AccrualLine:
    holding_id: str
    profit_target: Decimal
    profit_booked: Decimal
    profit_posted: Decimal
    fee_target: Decimal
    fee_booked: Decimal
    fee_posted: Decimal
    note: str = ""


@dataclass(frozen=True)
class AccrualRun:
    client_id: str
    as_of: date
    lines: list[AccrualLine]
    rent_invoices: list[str]
    skipped: list[str]

    @property
    def profit_posted(self) -> Decimal:
        return money(sum((line.profit_posted for line in self.lines), Decimal(0)))

    @property
    def fee_posted(self) -> Decimal:
        return money(sum((line.fee_posted for line in self.lines), Decimal(0)))

    @property
    def changed(self) -> bool:
        return bool(self.rent_invoices) or self.profit_posted != 0 or self.fee_posted != 0


def accrue_holding_profit(
    db: Session, holding: Holding, as_of: date, *, created_by: str
) -> Decimal:
    """Post the difference between profit earned to *as_of* and profit already booked."""
    target = holdings_svc.accrual_target(db, holding, as_of)
    booked = holdings_svc.income_recognised(db, holding, as_of)
    delta = money(target - booked)
    if delta == 0:
        return ZERO

    client = db.get(Client, holding.client_id)
    assert client is not None
    ctx = PostingContext(
        client=client,
        custody_account=holdings_svc.custody_account_for(db, holding),
        holding=holding,
        descriptions={"amount": f"Profit accrued to {as_of.isoformat()}"},
    )
    lines = build_lines(db, ctx, "PROFIT_ACCRUED", {"amount": abs(delta)})
    if delta < 0:
        lines = [replace(line, amount=-line.amount) for line in lines]
    post(
        db,
        entry_date=as_of,
        event=event_for("PROFIT_ACCRUED"),
        client_id=holding.client_id,
        currency=holding.currency,
        lines=lines,
        narrative=f"Profit accrued on {holding.id} to {as_of.isoformat()}",
        created_by=created_by,
    )
    return delta


def accrue_fee(db: Session, holding: Holding, as_of: date, *, created_by: str) -> Decimal:
    """Post the difference between the fee due on recognised income and the fee booked.

    The fee is a percentage of income *this system* has recognised, so opening accrued
    profit -- which was earned before go-live -- is never charged twice.
    """
    income = holdings_svc.income_recognised(db, holding, as_of)
    pct = holdings_svc.fee_rate(db, holding, as_of)
    target = round_money(income * pct)
    booked = holdings_svc.fee_charged(db, holding, as_of)
    delta = money(target - booked)
    if delta == 0:
        return ZERO

    client = db.get(Client, holding.client_id)
    assert client is not None
    ctx = PostingContext(
        client=client,
        custody_account=holdings_svc.custody_account_for(db, holding),
        holding=holding,
        descriptions={
            "amount": f"Management fee at {pct * 100:.4f}% of income to {as_of.isoformat()}"
        },
    )
    lines = build_lines(db, ctx, "FEE_ACCRUED", {"amount": abs(delta)})
    if delta < 0:
        lines = [replace(line, amount=-line.amount) for line in lines]
    post(
        db,
        entry_date=as_of,
        event=event_for("FEE_ACCRUED"),
        client_id=holding.client_id,
        currency=holding.currency,
        lines=lines,
        narrative=f"Management fee on {holding.id} to {as_of.isoformat()}",
        created_by=created_by,
    )
    return delta


def rent_reference(holding_id: str, month: date) -> str:
    return f"{RENT_PREFIX}-{holding_id}-{month.strftime('%Y-%m')}"


def months_to_invoice(holding: Holding, as_of: date) -> list[date]:
    """The first of each month that should be invoiced, from the month after start."""
    if holding.monthly_rent in (None, ZERO) or holding.accrual_start is None:
        return []
    start = holding.accrual_start
    year, month = start.year, start.month
    if month == 12:
        year, month = year + 1, 1
    else:
        month += 1
    out: list[date] = []
    while True:
        first = date(year, month, 1)
        if first > as_of:
            break
        if holding.maturity_date is not None and first > holding.maturity_date:
            break
        out.append(first)
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1
    return out


def invoice_rent(db: Session, holding: Holding, as_of: date, *, created_by: str) -> list[str]:
    """Invoice monthly rent for a property, once per month, by unique reference."""
    if holding.asset_class is not AssetClass.PROPERTY or holding.monthly_rent is None:
        return []
    client = db.get(Client, holding.client_id)
    assert client is not None

    raised: list[str] = []
    for first in months_to_invoice(holding, as_of):
        reference = rent_reference(holding.id, first)
        exists = db.execute(
            select(JournalEntry.id).where(JournalEntry.reference == reference)
        ).scalar_one_or_none()
        if exists is not None:
            continue
        ctx = PostingContext(
            client=client,
            custody_account=holdings_svc.custody_account_for(db, holding),
            holding=holding,
            descriptions={"amount": f"Rent for {first.strftime('%B %Y')}"},
        )
        lines = build_lines(db, ctx, "RENT_INVOICED", {"amount": holding.monthly_rent})
        post(
            db,
            entry_date=first,
            event=event_for("RENT_INVOICED"),
            client_id=holding.client_id,
            currency=holding.currency,
            lines=lines,
            narrative=f"Rent invoiced on {holding.id} for {first.strftime('%B %Y')}",
            reference=reference,
            created_by=created_by,
        )
        raised.append(reference)
    return raised


def run(db: Session, client_id: str, as_of: date, *, created_by: str) -> AccrualRun:
    """Accrue profit, invoice rent and charge fees for one client up to *as_of*."""
    lines: list[AccrualLine] = []
    rent_invoices: list[str] = []
    skipped: list[str] = []

    for holding in holdings_svc.client_holdings(db, client_id):
        if holding.status is not HoldingStatus.ACTIVE:
            continue
        if holding.is_placeholder or (
            holding.asset_class is not AssetClass.PROPERTY and holding.profit_rate is None
        ):
            skipped.append(f"{holding.id}: terms are still pending, so no profit can be accrued")
            continue

        rent_invoices.extend(invoice_rent(db, holding, as_of, created_by=created_by))

        profit_target = holdings_svc.accrual_target(db, holding, as_of)
        profit_booked_before = holdings_svc.income_recognised(db, holding, as_of)
        profit_posted = (
            accrue_holding_profit(db, holding, as_of, created_by=created_by)
            if holdings_svc.is_accruable(holding)
            else ZERO
        )

        fee_income = holdings_svc.income_recognised(db, holding, as_of)
        fee_target = round_money(fee_income * holdings_svc.fee_rate(db, holding, as_of))
        fee_booked_before = holdings_svc.fee_charged(db, holding, as_of)
        fee_posted = accrue_fee(db, holding, as_of, created_by=created_by)

        lines.append(
            AccrualLine(
                holding_id=holding.id,
                profit_target=profit_target,
                profit_booked=profit_booked_before,
                profit_posted=profit_posted,
                fee_target=fee_target,
                fee_booked=fee_booked_before,
                fee_posted=fee_posted,
            )
        )

    return AccrualRun(
        client_id=client_id,
        as_of=as_of,
        lines=lines,
        rent_invoices=rent_invoices,
        skipped=skipped,
    )


def true_up(
    db: Session,
    holding: Holding,
    *,
    on: date,
    amount: Decimal,
    created_by: str,
    reason: str,
) -> Decimal:
    """Recognise profit the counterparty actually paid, over and above the accrual.

    The reference marks the entry as a true-up so later accrual runs include it in
    their target instead of reversing it.
    """
    amount = money(amount)
    if amount == 0:
        return ZERO
    client = db.get(Client, holding.client_id)
    assert client is not None
    sequence = db.execute(
        select(JournalEntry.id).where(
            JournalEntry.reference.like(f"{holdings_svc.TRUE_UP_PREFIX}-{holding.id}-%")
        )
    ).all()
    reference = f"{holdings_svc.TRUE_UP_PREFIX}-{holding.id}-{len(sequence) + 1}"
    ctx = PostingContext(
        client=client,
        custody_account=holdings_svc.custody_account_for(db, holding),
        holding=holding,
        descriptions={"amount": reason},
    )
    lines = build_lines(db, ctx, "PROFIT_ACCRUED", {"amount": abs(amount)})
    if amount < 0:
        lines = [replace(line, amount=-line.amount) for line in lines]
    post(
        db,
        entry_date=on,
        event=LedgerEvent.PROFIT_ACCRUED,
        client_id=holding.client_id,
        currency=holding.currency,
        lines=lines,
        narrative=f"Profit true-up on {holding.id}: {reason}",
        reference=reference,
        created_by=created_by,
    )
    return amount
