"""Currency: daily rates, month-end revaluation and currency conversion.

IAS 21 in practice.  Every journal line already carries the rate it was posted at, so
revaluation is a matter of comparing the base amount on the books with what the
closing rate says the foreign currency balance is now worth, and posting the
difference.  Client capital and client profit are not revalued: the client's stake is
measured in base currency, and revaluing it would hide the gain or loss.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import BusinessRule, Conflict, NotFound
from app.ledger import balances
from app.ledger import fx as fx_rates
from app.ledger.posting import LineDraft, PostingContext, build_lines, post
from app.ledger.roles import Role, resolve
from app.ledger.rules import event_for
from app.models import AccountType, Client, CustodyAccount, FxRate, JournalEntry, LedgerEvent
from app.money import ZERO, convert, money
from app.services import audit

EXCLUDED_ROLES = (Role.CLIENT_CAPITAL, Role.CLIENT_PROFIT)


def record_rate(
    db: Session,
    *,
    currency: str,
    base_currency: str,
    rate_date: date,
    value: Decimal,
    source: str,
    entered_by: str,
) -> FxRate:
    if currency == base_currency:
        raise BusinessRule("a currency never needs a rate against itself")
    if value <= 0:
        raise BusinessRule("an exchange rate must be more than zero", value=str(value))
    existing = db.execute(
        select(FxRate).where(
            FxRate.currency == currency,
            FxRate.base_currency == base_currency,
            FxRate.rate_date == rate_date,
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise Conflict(
            f"a {currency}/{base_currency} rate for {rate_date.isoformat()} is already on file; "
            "correct it with a new dated rate",
            rate_date=rate_date.isoformat(),
        )
    row = FxRate(
        currency=currency,
        base_currency=base_currency,
        rate_date=rate_date,
        rate=value,
        source=source,
        entered_by=entered_by,
        created_by=entered_by,
    )
    db.add(row)
    db.flush()
    audit.record(
        db,
        user_id=entered_by,
        action="FX_RATE_RECORDED",
        entity="fx_rate",
        entity_id=row.id,
        detail={
            "currency": currency,
            "base_currency": base_currency,
            "rate_date": rate_date.isoformat(),
            "rate": f"{value:f}",
            "source": source,
        },
    )
    return row


# --- Month-end revaluation ---------------------------------------------------


@dataclass(frozen=True)
class RevaluationLine:
    account_code: str
    holding_id: str | None
    currency: str
    own_amount: Decimal
    base_before: Decimal
    base_after: Decimal

    @property
    def delta(self) -> Decimal:
        return money(self.base_after - self.base_before)


@dataclass(frozen=True)
class RevaluationResult:
    client_id: str
    as_of: date
    lines: list[RevaluationLine]
    entry: JournalEntry | None

    @property
    def net(self) -> Decimal:
        return money(sum((line.delta for line in self.lines), Decimal(0)))

    @property
    def changed(self) -> bool:
        return self.entry is not None


def revalue(
    db: Session, client_id: str, as_of: date, *, created_by: str, bypass_period_lock: bool = False
) -> RevaluationResult:
    """Restate every foreign-currency balance sheet balance at the closing rate."""
    client = db.get(Client, client_id)
    if client is None:
        raise NotFound(f"unknown client {client_id}", client_id=client_id)

    excluded = {resolve(db, client_id, role) for role in EXCLUDED_ROLES}

    rows = [
        row
        for row in balances.by_holding_currency(db, client_id=client_id, as_of=as_of)
        if row.type in (AccountType.ASSET, AccountType.LIABILITY)
        and row.currency != client.base_currency
        and row.account_code not in excluded
    ]

    reval_lines: list[RevaluationLine] = []
    drafts: list[LineDraft] = []
    for row in rows:
        assert row.currency is not None
        closing = fx_rates.rate_for(db, row.currency, client.base_currency, as_of)
        target = convert(row.amount, closing)
        line = RevaluationLine(
            account_code=row.account_code,
            holding_id=row.holding_id,
            currency=row.currency,
            own_amount=row.amount,
            base_before=row.base_amount,
            base_after=target,
        )
        if line.delta == 0:
            continue
        reval_lines.append(line)
        drafts.append(
            LineDraft(
                account_code=row.account_code,
                amount=ZERO,
                client_id=client_id,
                holding_id=row.holding_id,
                currency=row.currency,
                fx_rate=closing,
                base_amount=line.delta,
                description=(
                    f"Revalued {row.amount:.2f} {row.currency} at {closing:f} "
                    f"({line.base_before:.2f} -> {line.base_after:.2f})"
                ),
            )
        )

    if not drafts:
        return RevaluationResult(client_id=client_id, as_of=as_of, lines=[], entry=None)

    net = money(sum((line.delta for line in reval_lines), Decimal(0)))
    role = Role.FX_GAIN if net > 0 else Role.FX_LOSS
    drafts.append(
        LineDraft(
            account_code=resolve(db, client_id, role),
            amount=money(-net),
            client_id=client_id,
            currency=client.base_currency,
            fx_rate=Decimal("1.00000000"),
            base_amount=money(-net),
            description=f"Net exchange {'gain' if net > 0 else 'loss'} on revaluation",
        )
    )

    entry = post(
        db,
        entry_date=as_of,
        event=LedgerEvent.FX_REVALUATION,
        client_id=client_id,
        currency=client.base_currency,
        lines=drafts,
        narrative=f"Exchange revaluation at {as_of.isoformat()} closing rates",
        created_by=created_by,
        multi_currency=True,
        bypass_period_lock=bypass_period_lock,
    )
    audit.record(
        db,
        user_id=created_by,
        action="FX_REVALUATION",
        entity="journal_entry",
        entity_id=entry.id,
        client_id=client_id,
        detail={
            "as_of": as_of.isoformat(),
            "net": f"{net:.2f}",
            "lines": [
                {
                    "account_code": line.account_code,
                    "holding_id": line.holding_id,
                    "currency": line.currency,
                    "delta": f"{line.delta:.2f}",
                }
                for line in reval_lines
            ],
        },
    )
    return RevaluationResult(client_id=client_id, as_of=as_of, lines=reval_lines, entry=entry)


# --- Conversion --------------------------------------------------------------


def convert_currency(
    db: Session,
    *,
    client_id: str,
    from_account_id: str,
    to_account_id: str,
    sell: Decimal,
    buy: Decimal,
    on: date,
    agreed_rate: Decimal,
    created_by: str,
    instruction_id: int | None = None,
    reference: str | None = None,
) -> JournalEntry:
    """Sell one currency and buy another inside the same mandate.

    The two legs are booked at the day's official rates; the difference between them
    is the realised gain or loss against the rate the custodian actually dealt at.
    """
    client = db.get(Client, client_id)
    if client is None:
        raise NotFound(f"unknown client {client_id}", client_id=client_id)
    source = db.get(CustodyAccount, from_account_id)
    target = db.get(CustodyAccount, to_account_id)
    if source is None or target is None:
        raise NotFound("unknown custody account on an FX conversion")
    if source.client_id != client_id or target.client_id != client_id:
        raise BusinessRule(
            "an FX conversion must move money between two accounts of the same client",
            client_id=client_id,
        )
    if source.currency == target.currency:
        raise BusinessRule("an FX conversion needs two different currencies")
    if sell <= 0 or buy <= 0:
        raise BusinessRule("both sides of an FX conversion must be more than zero")

    ctx = PostingContext(
        client=client,
        custody_account=source,
        target_custody_account=target,
        descriptions={
            "sell": f"Sold {sell:.2f} {source.currency} at agreed {agreed_rate:f}",
            "buy": f"Bought {buy:.2f} {target.currency}",
        },
    )
    lines = build_lines(db, ctx, "FX_CONVERSION", {"sell": money(sell), "buy": money(buy)})
    entry = post(
        db,
        entry_date=on,
        event=event_for("FX_CONVERSION"),
        client_id=client_id,
        currency=source.currency,
        lines=lines,
        narrative=(
            f"Converted {sell:.2f} {source.currency} to {buy:.2f} {target.currency} "
            f"at agreed rate {agreed_rate:f}"
        ),
        reference=reference,
        instruction_id=instruction_id,
        created_by=created_by,
        multi_currency=True,
        allow_fx_difference=True,
    )
    audit.record(
        db,
        user_id=created_by,
        action="FX_CONVERSION",
        entity="journal_entry",
        entity_id=entry.id,
        client_id=client_id,
        detail={
            "sell": f"{sell:.2f} {source.currency}",
            "buy": f"{buy:.2f} {target.currency}",
            "agreed_rate": f"{agreed_rate:f}",
        },
    )
    return entry


def latest_rates(db: Session, base_currency: str, as_of: date) -> dict[str, Decimal]:
    """The newest rate on or before *as_of* for every currency quoted against *base*."""
    rows = db.execute(
        select(FxRate.currency, FxRate.rate_date, FxRate.rate)
        .where(FxRate.base_currency == base_currency, FxRate.rate_date <= as_of)
        .order_by(FxRate.currency, FxRate.rate_date)
    ).all()
    out: dict[str, Decimal] = {}
    for currency, _rate_date, value in rows:
        out[currency] = value
    return out
