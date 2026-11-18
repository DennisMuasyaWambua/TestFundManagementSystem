"""Balance queries.

Nothing in this system stores a balance.  Every figure on every screen, report and
statement is summed from ``journal_lines`` here, so the ledger is the only version of
the truth.  Amounts are signed: a debit balance is positive, a credit balance negative.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models import Account, AccountType, JournalEntry, JournalLine, LedgerEvent
from app.money import ZERO, money


def _scope(
    stmt: Select[Decimal | None],
    *,
    client_id: str | None,
    account_code: str | None = None,
    account_codes: list[str] | None = None,
    holding_id: str | None = None,
    currency: str | None = None,
    as_of: date | None = None,
    from_date: date | None = None,
    exclude_events: tuple[LedgerEvent, ...] = (),
    only_events: tuple[LedgerEvent, ...] = (),
) -> Select[Decimal | None]:
    stmt = stmt.join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
    if client_id is not None:
        stmt = stmt.where(JournalLine.client_id == client_id)
    if account_code is not None:
        stmt = stmt.where(JournalLine.account_code == account_code)
    if account_codes is not None:
        stmt = stmt.where(JournalLine.account_code.in_(account_codes))
    if holding_id is not None:
        stmt = stmt.where(JournalLine.holding_id == holding_id)
    if currency is not None:
        stmt = stmt.where(JournalLine.currency == currency)
    if as_of is not None:
        stmt = stmt.where(JournalEntry.entry_date <= as_of)
    if from_date is not None:
        stmt = stmt.where(JournalEntry.entry_date >= from_date)
    if exclude_events:
        stmt = stmt.where(JournalEntry.event.notin_([str(e) for e in exclude_events]))
    if only_events:
        stmt = stmt.where(JournalEntry.event.in_([str(e) for e in only_events]))
    return stmt


def balance(
    db: Session,
    *,
    client_id: str | None,
    account_code: str | None = None,
    account_codes: list[str] | None = None,
    holding_id: str | None = None,
    currency: str | None = None,
    as_of: date | None = None,
    from_date: date | None = None,
    base: bool = False,
    exclude_events: tuple[LedgerEvent, ...] = (),
    only_events: tuple[LedgerEvent, ...] = (),
) -> Decimal:
    """Signed balance: debits minus credits."""
    column = JournalLine.base_amount if base else JournalLine.amount
    stmt = _scope(
        select(func.sum(column)),
        client_id=client_id,
        account_code=account_code,
        account_codes=account_codes,
        holding_id=holding_id,
        currency=currency,
        as_of=as_of,
        from_date=from_date,
        exclude_events=exclude_events,
        only_events=only_events,
    )
    # SUM() over no rows is NULL, and SUM() of an empty scope returns a single NULL
    # row: both mean "no movement", which is a zero balance, not a missing one.
    value = db.scalars(stmt).one_or_none()
    return money(value) if value is not None else ZERO


@dataclass(frozen=True)
class AccountBalance:
    account_code: str
    name: str
    type: AccountType
    amount: Decimal
    base_amount: Decimal
    currency: str | None = None
    holding_id: str | None = None

    @property
    def presented(self) -> Decimal:
        """The balance the way a reader expects it: positive on its normal side."""
        if self.type in (AccountType.ASSET, AccountType.EXPENSE):
            return self.base_amount
        return -self.base_amount


def by_account(
    db: Session,
    *,
    client_id: str | None,
    as_of: date | None = None,
    from_date: date | None = None,
    types: tuple[AccountType, ...] = (),
    exclude_events: tuple[LedgerEvent, ...] = (),
    include_zero: bool = False,
) -> list[AccountBalance]:
    """One row per account with a balance, ordered by account code."""
    stmt = (
        select(
            JournalLine.account_code,
            Account.name,
            Account.type,
            func.sum(JournalLine.amount),
            func.sum(JournalLine.base_amount),
        )
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .join(Account, Account.code == JournalLine.account_code)
        .group_by(JournalLine.account_code, Account.name, Account.type)
        .order_by(JournalLine.account_code)
    )
    if client_id is not None:
        stmt = stmt.where(JournalLine.client_id == client_id)
    if as_of is not None:
        stmt = stmt.where(JournalEntry.entry_date <= as_of)
    if from_date is not None:
        stmt = stmt.where(JournalEntry.entry_date >= from_date)
    if types:
        stmt = stmt.where(Account.type.in_([str(t) for t in types]))
    if exclude_events:
        stmt = stmt.where(JournalEntry.event.notin_([str(e) for e in exclude_events]))

    rows: list[AccountBalance] = []
    for code, name, acc_type, amount, base_amount in db.execute(stmt):
        row = AccountBalance(
            account_code=code,
            name=name,
            type=AccountType(acc_type),
            amount=money(amount or 0),
            base_amount=money(base_amount or 0),
        )
        if include_zero or row.amount != 0 or row.base_amount != 0:
            rows.append(row)
    return rows


def by_holding_currency(
    db: Session,
    *,
    client_id: str,
    as_of: date,
    account_codes: list[str] | None = None,
) -> list[AccountBalance]:
    """Balances grouped by (account, holding, currency) -- the FX revaluation unit."""
    stmt = (
        select(
            JournalLine.account_code,
            Account.name,
            Account.type,
            JournalLine.holding_id,
            JournalLine.currency,
            func.sum(JournalLine.amount),
            func.sum(JournalLine.base_amount),
        )
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .join(Account, Account.code == JournalLine.account_code)
        .where(JournalLine.client_id == client_id, JournalEntry.entry_date <= as_of)
        .group_by(
            JournalLine.account_code,
            Account.name,
            Account.type,
            JournalLine.holding_id,
            JournalLine.currency,
        )
        .order_by(JournalLine.account_code, JournalLine.holding_id, JournalLine.currency)
    )
    if account_codes is not None:
        stmt = stmt.where(JournalLine.account_code.in_(account_codes))

    rows: list[AccountBalance] = []
    for code, name, acc_type, holding_id, currency, amount, base_amount in db.execute(stmt):
        rows.append(
            AccountBalance(
                account_code=code,
                name=name,
                type=AccountType(acc_type),
                amount=money(amount or 0),
                base_amount=money(base_amount or 0),
                currency=currency,
                holding_id=holding_id,
            )
        )
    return rows


def trial_balance(
    db: Session, *, as_of: date, client_id: str | None = None
) -> list[AccountBalance]:
    return by_account(db, client_id=client_id, as_of=as_of)
