"""Money in: everything the custodian credits to a client's account.

No instruction letter is needed for money coming in, but every receipt quotes the
custodian's own advice reference so the ledger entry can be traced back to the
statement it came from.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.errors import BusinessRule, Conflict, NotFound
from app.ledger.posting import PostingContext, build_lines, post
from app.ledger.rules import event_for
from app.models import (
    AssetClass,
    Client,
    CustodyAccount,
    Holding,
    HoldingStatus,
    JournalEntry,
    LedgerEvent,
    RecordStatus,
)
from app.money import ZERO, money
from app.services import accruals, audit
from app.services import holdings as holdings_svc
from app.services import valuation as valuation_svc


@dataclass(frozen=True)
class Receipt:
    entry: JournalEntry
    holding_id: str | None = None
    true_up: Decimal = ZERO


def _client(db: Session, client_id: str) -> Client:
    client = db.get(Client, client_id)
    if client is None:
        raise NotFound(f"unknown client {client_id}", client_id=client_id)
    return client


def _custody(db: Session, custody_account_id: str, client_id: str) -> CustodyAccount:
    account = db.get(CustodyAccount, custody_account_id)
    if account is None:
        raise NotFound(
            f"unknown custody account {custody_account_id}",
            custody_account_id=custody_account_id,
        )
    if account.client_id != client_id:
        raise NotFound(
            f"unknown custody account {custody_account_id}",
            custody_account_id=custody_account_id,
        )
    if account.status is not RecordStatus.ACTIVE:
        raise BusinessRule(
            f"custody account {custody_account_id} is {account.status}",
            custody_account_id=custody_account_id,
        )
    return account


def _require_positive(name: str, value: Decimal) -> Decimal:
    amount = money(value)
    if amount <= 0:
        raise BusinessRule(f"{name} must be more than zero", field=name, value=str(amount))
    return amount


def _audit_receipt(
    db: Session,
    *,
    created_by: str,
    action: str,
    client_id: str,
    entry: JournalEntry,
    advice_ref: str,
    detail: dict[str, object],
) -> None:
    audit.record(
        db,
        user_id=created_by,
        action=action,
        entity="journal_entry",
        entity_id=entry.id,
        client_id=client_id,
        detail={"custodian_advice_ref": advice_ref, **detail},
    )


def record_contribution(
    db: Session,
    *,
    client_id: str,
    custody_account_id: str,
    amount: Decimal,
    value_date: date,
    advice_ref: str,
    created_by: str,
    narrative: str = "",
) -> Receipt:
    """A client pays money into its mandate."""
    client = _client(db, client_id)
    custody = _custody(db, custody_account_id, client_id)
    value = _require_positive("amount", amount)
    if not advice_ref.strip():
        raise BusinessRule("the custodian's credit advice reference is required")

    ctx = PostingContext(
        client=client,
        custody_account=custody,
        descriptions={"amount": narrative or "Client contribution"},
    )
    lines = build_lines(db, ctx, "CLIENT_CONTRIBUTION", {"amount": value})
    entry = post(
        db,
        entry_date=value_date,
        event=event_for("CLIENT_CONTRIBUTION"),
        client_id=client_id,
        currency=custody.currency,
        lines=lines,
        narrative=narrative or f"Contribution received, advice {advice_ref}",
        reference=advice_ref,
        created_by=created_by,
    )
    _audit_receipt(
        db,
        created_by=created_by,
        action="CONTRIBUTION_RECORDED",
        client_id=client_id,
        entry=entry,
        advice_ref=advice_ref,
        detail={"amount": f"{value:.2f}", "currency": custody.currency},
    )
    return Receipt(entry=entry)


def _accrue_to_day_before(
    db: Session, holding: Holding, value_date: date, *, created_by: str
) -> None:
    """Profit paid on day D covers the days up to D-1, so accrue to D-1 first."""
    if holdings_svc.is_accruable(holding):
        accruals.accrue_holding_profit(
            db, holding, value_date - timedelta(days=1), created_by=created_by
        )
        accruals.accrue_fee(db, holding, value_date - timedelta(days=1), created_by=created_by)


def record_profit(
    db: Session,
    *,
    holding_id: str,
    gross: Decimal,
    wht: Decimal,
    value_date: date,
    advice_ref: str,
    created_by: str,
) -> Receipt:
    """A profit distribution or financing profit instalment lands in the account."""
    holding = holdings_svc.get_holding(db, holding_id)
    if holding.status is not HoldingStatus.ACTIVE:
        raise Conflict(f"holding {holding_id} is {holding.status}", status=str(holding.status))
    gross_amount = _require_positive("gross", gross)
    wht_amount = money(wht)
    if wht_amount < 0:
        raise BusinessRule("withholding tax cannot be negative")
    if wht_amount > gross_amount:
        raise BusinessRule("withholding tax cannot exceed the gross profit")

    _accrue_to_day_before(db, holding, value_date, created_by=created_by)

    accrued = holdings_svc.accrued_profit(db, holding, value_date)
    true_up = ZERO
    if gross_amount > accrued:
        true_up = accruals.true_up(
            db,
            holding,
            on=value_date,
            amount=money(gross_amount - accrued),
            created_by=created_by,
            reason=(
                f"counterparty paid {gross_amount:.2f}, {gross_amount - accrued:.2f} more than "
                "accrued"
            ),
        )
        accruals.accrue_fee(db, holding, value_date, created_by=created_by)

    client = _client(db, holding.client_id)
    ctx = PostingContext(
        client=client,
        custody_account=holdings_svc.custody_account_for(db, holding),
        holding=holding,
        descriptions={
            "net": "Profit received, net of tax at source",
            "wht": "Withholding tax deducted at source",
            "gross": "Accrued profit settled",
        },
    )
    lines = build_lines(
        db,
        ctx,
        "PROFIT_RECEIVED",
        {"net": money(gross_amount - wht_amount), "wht": wht_amount, "gross": gross_amount},
    )
    entry = post(
        db,
        entry_date=value_date,
        event=event_for("PROFIT_RECEIVED"),
        client_id=holding.client_id,
        currency=holding.currency,
        lines=lines,
        narrative=f"Profit received on {holding_id}, advice {advice_ref}",
        reference=advice_ref,
        created_by=created_by,
    )
    _audit_receipt(
        db,
        created_by=created_by,
        action="PROFIT_RECEIVED",
        client_id=holding.client_id,
        entry=entry,
        advice_ref=advice_ref,
        detail={
            "holding_id": holding_id,
            "gross": f"{gross_amount:.2f}",
            "wht": f"{wht_amount:.2f}",
            "true_up": f"{true_up:.2f}",
        },
    )
    return Receipt(entry=entry, holding_id=holding_id, true_up=true_up)


def record_principal(
    db: Session,
    *,
    holding_id: str,
    amount: Decimal,
    value_date: date,
    advice_ref: str,
    created_by: str,
) -> Receipt:
    """A financing principal instalment is repaid."""
    holding = holdings_svc.get_holding(db, holding_id)
    if holding.status is not HoldingStatus.ACTIVE:
        raise Conflict(f"holding {holding_id} is {holding.status}", status=str(holding.status))
    value = _require_positive("amount", amount)

    _accrue_to_day_before(db, holding, value_date, created_by=created_by)

    outstanding = holdings_svc.outstanding(db, holding, value_date)
    if value > outstanding:
        raise BusinessRule(
            f"repayment of {value:.2f} is more than the {outstanding:.2f} outstanding on "
            f"{holding_id}",
            holding_id=holding_id,
            outstanding=f"{outstanding:.2f}",
        )

    client = _client(db, holding.client_id)
    ctx = PostingContext(
        client=client,
        custody_account=holdings_svc.custody_account_for(db, holding),
        holding=holding,
        descriptions={"amount": "Principal repaid"},
    )
    lines = build_lines(db, ctx, "PRINCIPAL_RECEIVED", {"amount": value})
    entry = post(
        db,
        entry_date=value_date,
        event=event_for("PRINCIPAL_RECEIVED"),
        client_id=holding.client_id,
        currency=holding.currency,
        lines=lines,
        narrative=f"Principal repaid on {holding_id}, advice {advice_ref}",
        reference=advice_ref,
        created_by=created_by,
    )

    remaining = holdings_svc.outstanding(db, holding, value_date)
    remaining_accrued = holdings_svc.accrued_profit(db, holding, value_date)
    if remaining == 0 and remaining_accrued == 0:
        holding.status = HoldingStatus.MATURED
        holding.updated_by = created_by

    _audit_receipt(
        db,
        created_by=created_by,
        action="PRINCIPAL_RECEIVED",
        client_id=holding.client_id,
        entry=entry,
        advice_ref=advice_ref,
        detail={
            "holding_id": holding_id,
            "amount": f"{value:.2f}",
            "outstanding_after": f"{remaining:.2f}",
            "status": str(holding.status),
        },
    )
    return Receipt(entry=entry, holding_id=holding_id)


def record_maturity(
    db: Session,
    *,
    holding_id: str,
    principal: Decimal,
    profit: Decimal,
    wht: Decimal,
    value_date: date,
    advice_ref: str,
    created_by: str,
) -> Receipt:
    """A Wakala or Sukuk matures, or a property is sold.

    The holding is accrued to maturity, then -- for anything carried at fair value --
    revalued to the proceeds so the fair value adjustment clears, and finally the
    profit is trued up to the figure the counterparty actually paid.  After this the
    investment, its fair value adjustment and its accrued profit are all zero.
    """
    holding = holdings_svc.get_holding(db, holding_id)
    if holding.status is not HoldingStatus.ACTIVE:
        raise Conflict(f"holding {holding_id} is {holding.status}", status=str(holding.status))
    principal_amount = _require_positive("principal", principal)
    profit_amount = money(profit)
    wht_amount = money(wht)
    if profit_amount < 0:
        raise BusinessRule("profit at maturity cannot be negative")
    if wht_amount < 0 or wht_amount > profit_amount:
        raise BusinessRule("withholding tax must be between zero and the profit paid")

    if holdings_svc.is_accruable(holding):
        accruals.accrue_holding_profit(db, holding, value_date, created_by=created_by)

    if holding.asset_class in valuation_svc.FAIR_VALUED:
        valuation_svc.revalue_to(
            db,
            holding,
            on=value_date,
            target=principal_amount,
            created_by=created_by,
            narrative=f"Revalued to disposal proceeds on {holding_id}",
        )

    accrued = holdings_svc.accrued_profit(db, holding, value_date)
    true_up = ZERO
    if profit_amount != accrued:
        true_up = accruals.true_up(
            db,
            holding,
            on=value_date,
            amount=money(profit_amount - accrued),
            created_by=created_by,
            reason=(
                f"counterparty paid profit of {profit_amount:.2f} against {accrued:.2f} accrued"
            ),
        )

    accruals.accrue_fee(db, holding, value_date, created_by=created_by)

    cost = holdings_svc.outstanding(db, holding, value_date)
    fv_adjustment = holdings_svc.fair_value_adjustment(db, holding, value_date)
    accrued = holdings_svc.accrued_profit(db, holding, value_date)

    client = _client(db, holding.client_id)
    ctx = PostingContext(
        client=client,
        custody_account=holdings_svc.custody_account_for(db, holding),
        holding=holding,
        descriptions={
            "net": "Principal and profit received, net of tax at source",
            "wht": "Withholding tax deducted at source",
            "cost": "Investment at cost released",
            "fv_adjustment": "Fair value adjustment cleared on disposal",
            "profit": "Accrued profit settled",
        },
    )
    lines = build_lines(
        db,
        ctx,
        "INVESTMENT_MATURED",
        {
            "net": money(principal_amount + profit_amount - wht_amount),
            "wht": wht_amount,
            "cost": cost,
            "fv_adjustment": fv_adjustment,
            "profit": accrued,
        },
    )
    entry = post(
        db,
        entry_date=value_date,
        event=event_for("INVESTMENT_MATURED"),
        client_id=holding.client_id,
        currency=holding.currency,
        lines=lines,
        narrative=f"Maturity of {holding_id}, advice {advice_ref}",
        reference=advice_ref,
        created_by=created_by,
    )

    holding.status = HoldingStatus.MATURED
    holding.updated_by = created_by
    db.flush()

    _audit_receipt(
        db,
        created_by=created_by,
        action="INVESTMENT_MATURED",
        client_id=holding.client_id,
        entry=entry,
        advice_ref=advice_ref,
        detail={
            "holding_id": holding_id,
            "principal": f"{principal_amount:.2f}",
            "profit": f"{profit_amount:.2f}",
            "wht": f"{wht_amount:.2f}",
            "true_up": f"{true_up:.2f}",
        },
    )
    return Receipt(entry=entry, holding_id=holding_id, true_up=true_up)


def record_rent(
    db: Session,
    *,
    holding_id: str,
    gross: Decimal,
    wht: Decimal,
    value_date: date,
    advice_ref: str,
    created_by: str,
) -> Receipt:
    """Rent received from a tenant, never more than has been invoiced and is unpaid."""
    holding = holdings_svc.get_holding(db, holding_id)
    if holding.asset_class is not AssetClass.PROPERTY:
        raise BusinessRule(f"{holding_id} is not an investment property", holding_id=holding_id)
    gross_amount = _require_positive("gross", gross)
    wht_amount = money(wht)
    if wht_amount < 0 or wht_amount > gross_amount:
        raise BusinessRule("withholding tax must be between zero and the rent received")

    outstanding_rent = holdings_svc.rent_receivable(db, holding, value_date)
    if gross_amount > outstanding_rent:
        raise BusinessRule(
            f"rent received of {gross_amount:.2f} is more than the {outstanding_rent:.2f} "
            "invoiced and unpaid",
            holding_id=holding_id,
            invoiced_unpaid=f"{outstanding_rent:.2f}",
        )

    client = _client(db, holding.client_id)
    ctx = PostingContext(
        client=client,
        custody_account=holdings_svc.custody_account_for(db, holding),
        holding=holding,
        descriptions={
            "net": "Rent received, net of tax at source",
            "wht": "Withholding tax deducted at source",
            "gross": "Rent receivable settled",
        },
    )
    lines = build_lines(
        db,
        ctx,
        "RENT_RECEIVED",
        {"net": money(gross_amount - wht_amount), "wht": wht_amount, "gross": gross_amount},
    )
    entry = post(
        db,
        entry_date=value_date,
        event=event_for("RENT_RECEIVED"),
        client_id=holding.client_id,
        currency=holding.currency,
        lines=lines,
        narrative=f"Rent received on {holding_id}, advice {advice_ref}",
        reference=advice_ref,
        created_by=created_by,
    )
    _audit_receipt(
        db,
        created_by=created_by,
        action="RENT_RECEIVED",
        client_id=holding.client_id,
        entry=entry,
        advice_ref=advice_ref,
        detail={"holding_id": holding_id, "gross": f"{gross_amount:.2f}"},
    )
    return Receipt(entry=entry, holding_id=holding_id)


def record_tenant_deposit(
    db: Session,
    *,
    holding_id: str,
    amount: Decimal,
    value_date: date,
    advice_ref: str,
    created_by: str,
) -> Receipt:
    """A refundable tenant deposit: the client's cash goes up and so does a liability."""
    holding = holdings_svc.get_holding(db, holding_id)
    if holding.asset_class is not AssetClass.PROPERTY:
        raise BusinessRule(f"{holding_id} is not an investment property", holding_id=holding_id)
    value = _require_positive("amount", amount)

    client = _client(db, holding.client_id)
    ctx = PostingContext(
        client=client,
        custody_account=holdings_svc.custody_account_for(db, holding),
        holding=holding,
        descriptions={"amount": "Tenant deposit held"},
    )
    lines = build_lines(db, ctx, "TENANT_DEPOSIT_RECEIVED", {"amount": value})
    entry = post(
        db,
        entry_date=value_date,
        event=event_for("TENANT_DEPOSIT_RECEIVED"),
        client_id=holding.client_id,
        currency=holding.currency,
        lines=lines,
        narrative=f"Tenant deposit received on {holding_id}, advice {advice_ref}",
        reference=advice_ref,
        created_by=created_by,
    )
    _audit_receipt(
        db,
        created_by=created_by,
        action="TENANT_DEPOSIT_RECEIVED",
        client_id=holding.client_id,
        entry=entry,
        advice_ref=advice_ref,
        detail={"holding_id": holding_id, "amount": f"{value:.2f}"},
    )
    return Receipt(entry=entry, holding_id=holding_id)


def write_off(
    db: Session,
    *,
    holding_id: str,
    on: date,
    reason: str,
    created_by: str,
) -> Receipt:
    """Write off private financing that will not be repaid."""
    holding = holdings_svc.get_holding(db, holding_id)
    if holding.asset_class is not AssetClass.PRIVATE_FINANCING:
        raise BusinessRule(
            "only private financing can be written off",
            holding_id=holding_id,
            asset_class=str(holding.asset_class),
        )
    if holding.status is not HoldingStatus.ACTIVE:
        raise Conflict(f"holding {holding_id} is {holding.status}", status=str(holding.status))
    if not reason.strip():
        raise BusinessRule("a write-off needs a reason")

    principal = holdings_svc.outstanding(db, holding, on)
    accrued = holdings_svc.accrued_profit(db, holding, on)
    if principal == 0 and accrued == 0:
        raise Conflict(f"nothing is outstanding on {holding_id}", holding_id=holding_id)

    client = _client(db, holding.client_id)
    ctx = PostingContext(
        client=client,
        custody_account=holdings_svc.custody_account_for(db, holding),
        holding=holding,
        descriptions={
            "amount": f"Written off: {reason}",
            "principal": "Principal written off",
            "accrued": "Accrued profit written off",
        },
    )
    lines = build_lines(
        db,
        ctx,
        "FINANCING_WRITE_OFF",
        {"amount": money(principal + accrued), "principal": principal, "accrued": accrued},
    )
    entry = post(
        db,
        entry_date=on,
        event=event_for("FINANCING_WRITE_OFF"),
        client_id=holding.client_id,
        currency=holding.currency,
        lines=lines,
        narrative=f"Write-off of {holding_id}: {reason}",
        created_by=created_by,
    )
    holding.status = HoldingStatus.WRITTEN_OFF
    holding.updated_by = created_by
    db.flush()
    audit.record(
        db,
        user_id=created_by,
        action="FINANCING_WRITTEN_OFF",
        entity="holding",
        entity_id=holding_id,
        client_id=holding.client_id,
        detail={
            "principal": f"{principal:.2f}",
            "accrued": f"{accrued:.2f}",
            "reason": reason,
            "journal_entry_id": entry.id,
        },
    )
    return Receipt(entry=entry, holding_id=holding_id)


__all__ = [
    "LedgerEvent",
    "Receipt",
    "record_contribution",
    "record_maturity",
    "record_principal",
    "record_profit",
    "record_rent",
    "record_tenant_deposit",
    "write_off",
]
