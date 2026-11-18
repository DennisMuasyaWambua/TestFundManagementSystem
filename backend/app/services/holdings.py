"""Derived figures for a holding.

A holding row stores its *terms*.  Every balance -- outstanding principal, accrued
profit, fair value adjustment, income recognised, fee charged -- is summed from the
ledger here, in the holding's own currency.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import NotFound
from app.ledger import balances
from app.ledger.roles import Role, class_role, resolve
from app.models import (
    AssetClass,
    Client,
    CustodyAccount,
    Holding,
    HoldingStatus,
    JournalEntry,
    JournalLine,
    LedgerEvent,
    MandateFee,
)
from app.money import ZERO, money, round_money

TRUE_UP_PREFIX = "TRUEUP"
RENT_PREFIX = "RENT"


def get_holding(db: Session, holding_id: str) -> Holding:
    holding = db.get(Holding, holding_id)
    if holding is None:
        raise NotFound(f"unknown holding {holding_id}", holding_id=holding_id)
    return holding


def custody_account_for(db: Session, holding: Holding) -> CustodyAccount:
    account = db.get(CustodyAccount, holding.custody_account_id)
    if account is None:  # pragma: no cover - foreign key in practice
        raise NotFound(
            f"holding {holding.id} points at unknown custody account {holding.custody_account_id}",
            holding_id=holding.id,
        )
    return account


def investment_account(db: Session, holding: Holding) -> str:
    return resolve(
        db,
        holding.client_id,
        Role.INVESTMENT,
        custody_account=custody_account_for(db, holding),
        asset_class=holding.asset_class,
    )


def income_account(db: Session, holding: Holding) -> str:
    return resolve(db, holding.client_id, class_role(holding.asset_class, Role.INCOME))


def fee_account(db: Session, holding: Holding) -> str:
    return resolve(db, holding.client_id, class_role(holding.asset_class, Role.FEE_EXPENSE))


def fv_account(db: Session, holding: Holding) -> str:
    return resolve(db, holding.client_id, class_role(holding.asset_class, Role.FV_ADJUSTMENT))


def accrued_account(db: Session, holding: Holding) -> str:
    return resolve(db, holding.client_id, Role.ACCRUED_INCOME)


def rent_receivable_account(db: Session, holding: Holding) -> str:
    return resolve(db, holding.client_id, Role.RENT_RECEIVABLE)


# --- Ledger-derived balances -------------------------------------------------


def outstanding(db: Session, holding: Holding, as_of: date | None = None) -> Decimal:
    """Principal still invested, in the holding's own currency."""
    return balances.balance(
        db,
        client_id=holding.client_id,
        account_code=investment_account(db, holding),
        holding_id=holding.id,
        as_of=as_of,
    )


def accrued_profit(db: Session, holding: Holding, as_of: date | None = None) -> Decimal:
    """Profit earned but not yet paid by the counterparty."""
    return balances.balance(
        db,
        client_id=holding.client_id,
        account_code=accrued_account(db, holding),
        holding_id=holding.id,
        as_of=as_of,
    )


def rent_receivable(db: Session, holding: Holding, as_of: date | None = None) -> Decimal:
    return balances.balance(
        db,
        client_id=holding.client_id,
        account_code=rent_receivable_account(db, holding),
        holding_id=holding.id,
        as_of=as_of,
    )


def fair_value_adjustment(db: Session, holding: Holding, as_of: date | None = None) -> Decimal:
    if holding.asset_class not in (AssetClass.SUKUK, AssetClass.PROPERTY):
        return ZERO
    return balances.balance(
        db,
        client_id=holding.client_id,
        account_code=fv_account(db, holding),
        holding_id=holding.id,
        as_of=as_of,
    )


def income_recognised(
    db: Session, holding: Holding, as_of: date | None = None, *, reference_prefix: str | None = None
) -> Decimal:
    """Income this system has recognised for the holding, as a positive amount."""
    stmt = (
        select(func.sum(JournalLine.amount))
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .where(
            JournalLine.client_id == holding.client_id,
            JournalLine.holding_id == holding.id,
            JournalLine.account_code == income_account(db, holding),
            JournalEntry.event != str(LedgerEvent.MONTH_END_CLOSE),
        )
    )
    if as_of is not None:
        stmt = stmt.where(JournalEntry.entry_date <= as_of)
    if reference_prefix is not None:
        stmt = stmt.where(JournalEntry.reference.like(f"{reference_prefix}%"))
    value = db.execute(stmt).scalar_one_or_none()
    return -money(value) if value is not None else ZERO


def fee_charged(db: Session, holding: Holding, as_of: date | None = None) -> Decimal:
    """Management fee charged on this holding's income, as a positive amount."""
    return balances.balance(
        db,
        client_id=holding.client_id,
        account_code=fee_account(db, holding),
        holding_id=holding.id,
        as_of=as_of,
        exclude_events=(LedgerEvent.MONTH_END_CLOSE,),
    )


def fee_rate(db: Session, holding: Holding, on: date) -> Decimal:
    """The management fee percentage in force for this mandate and asset class."""
    value = db.execute(
        select(MandateFee.fee_pct_of_income)
        .where(
            MandateFee.client_id == holding.client_id,
            MandateFee.asset_class == holding.asset_class,
            MandateFee.effective_from <= on,
        )
        .order_by(MandateFee.effective_from.desc())
        .limit(1)
    ).scalar_one_or_none()
    if value is None:
        raise NotFound(
            f"no management fee rate for {holding.client_id} {holding.asset_class} "
            f"on {on.isoformat()}",
            client_id=holding.client_id,
            asset_class=str(holding.asset_class),
        )
    return value


# --- Accrual arithmetic ------------------------------------------------------


@dataclass(frozen=True)
class PrincipalSegment:
    start: date
    end: date
    outstanding: Decimal

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


def accrual_end(holding: Holding, as_of: date) -> date | None:
    """The last day that earns profit: profit paid on day D covers days up to D-1."""
    if holding.accrual_start is None:
        return None
    last = as_of
    if holding.maturity_date is not None:
        last = min(last, holding.maturity_date - timedelta(days=1))
    return last if last >= holding.accrual_start else None


def principal_segments(db: Session, holding: Holding, as_of: date) -> list[PrincipalSegment]:
    """The outstanding principal over time, as constant-balance segments.

    Part repayments reduce the principal from their value date, so the accrual uses
    the balance as it stood on each day rather than the original face amount.
    """
    end = accrual_end(holding, as_of)
    if end is None or holding.accrual_start is None:
        return []

    movements = db.execute(
        select(JournalEntry.entry_date, func.sum(JournalLine.amount))
        .join(JournalLine, JournalLine.entry_id == JournalEntry.id)
        .where(
            JournalLine.holding_id == holding.id,
            JournalLine.account_code == investment_account(db, holding),
            JournalEntry.entry_date <= end,
        )
        .group_by(JournalEntry.entry_date)
        .order_by(JournalEntry.entry_date)
    ).all()

    running = ZERO
    timeline: list[tuple[date, Decimal]] = []
    for entry_date, delta in movements:
        running = money(running + money(delta or 0))
        timeline.append((entry_date, running))

    segments: list[PrincipalSegment] = []
    cursor = holding.accrual_start
    current = ZERO
    for moved_on, level in timeline:
        if moved_on <= cursor:
            current = level
            continue
        if moved_on > end:
            break
        segments.append(PrincipalSegment(cursor, moved_on - timedelta(days=1), current))
        cursor = moved_on
        current = level
    if cursor <= end:
        segments.append(PrincipalSegment(cursor, end, current))
    return [seg for seg in segments if seg.days > 0 and seg.outstanding != 0]


def system_accrued_profit(db: Session, holding: Holding, as_of: date) -> Decimal:
    """Profit this system has earned on the holding from ``accrual_start`` to *as_of*.

    Opening accrued profit, which covers every day up to and including the cutover
    date, is deliberately excluded: this is the system's own accrual, which starts the
    day after cutover.
    """
    if holding.profit_rate is None or holding.asset_class is AssetClass.PROPERTY:
        return ZERO
    scale = holding.accrual_nominal_scale
    basis = Decimal(holding.day_basis)
    acc = Decimal(0)
    for segment in principal_segments(db, holding, as_of):
        acc += segment.outstanding * scale * holding.profit_rate * Decimal(segment.days) / basis
    return round_money(acc)


def profit_to_date(db: Session, holding: Holding, as_of: date) -> Decimal:
    """Opening accrued profit plus everything the system has accrued since."""
    return money(holding.opening_accrued + system_accrued_profit(db, holding, as_of))


def accrual_target(db: Session, holding: Holding, as_of: date) -> Decimal:
    """What cumulative recognised income should be, including any true-ups booked."""
    true_ups = income_recognised(db, holding, as_of, reference_prefix=TRUE_UP_PREFIX)
    return money(system_accrued_profit(db, holding, as_of) + true_ups)


def is_accruable(holding: Holding) -> bool:
    return (
        holding.status is HoldingStatus.ACTIVE
        and holding.asset_class is not AssetClass.PROPERTY
        and holding.profit_rate is not None
        and holding.accrual_start is not None
    )


# --- Summary for screens and reports ----------------------------------------


@dataclass(frozen=True)
class HoldingSummary:
    holding: Holding
    outstanding: Decimal
    accrued_profit: Decimal
    rent_receivable: Decimal
    fair_value_adjustment: Decimal
    income_recognised: Decimal
    fee_charged: Decimal
    profit_to_date: Decimal

    @property
    def fair_value(self) -> Decimal:
        return money(self.outstanding + self.fair_value_adjustment)


def summarise(db: Session, holding: Holding, as_of: date) -> HoldingSummary:
    return HoldingSummary(
        holding=holding,
        outstanding=outstanding(db, holding, as_of),
        accrued_profit=accrued_profit(db, holding, as_of),
        rent_receivable=rent_receivable(db, holding, as_of),
        fair_value_adjustment=fair_value_adjustment(db, holding, as_of),
        income_recognised=income_recognised(db, holding, as_of),
        fee_charged=fee_charged(db, holding, as_of),
        profit_to_date=profit_to_date(db, holding, as_of),
    )


def client_holdings(
    db: Session,
    client_id: str,
    *,
    asset_class: AssetClass | None = None,
    status: HoldingStatus | None = None,
) -> list[Holding]:
    stmt = select(Holding).where(Holding.client_id == client_id).order_by(Holding.id)
    if asset_class is not None:
        stmt = stmt.where(Holding.asset_class == asset_class)
    if status is not None:
        stmt = stmt.where(Holding.status == status)
    return list(db.execute(stmt).scalars())


def base_currency(db: Session, client_id: str) -> str:
    client = db.get(Client, client_id)
    if client is None:
        raise NotFound(f"unknown client {client_id}", client_id=client_id)
    return client.base_currency
