"""``post()`` -- the only way anything reaches the ledger.

Every journal entry has two or more lines; each line carries a signed amount (debit
positive, credit negative), its own currency, the FX rate used and the base currency
amount.  A single-currency entry sums to exactly zero in its own currency; every entry
sums to exactly zero in the client's base currency.

The validation order below is the order given in section 6 of the build specification.
Any failure rejects the whole entry.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import (
    AccountNotPostable,
    BusinessRule,
    HoldingRequired,
    NotFound,
    PeriodLocked,
    SegregationBreach,
    UnbalancedEntry,
)
from app.ledger import fx
from app.ledger.roles import Role, client_owned_accounts, resolve
from app.ledger.rules import rules_for
from app.models import (
    Account,
    AccountType,
    AssetClass,
    Client,
    CustodyAccount,
    Holding,
    JournalEntry,
    JournalLine,
    LedgerEvent,
    PeriodLock,
    RecordStatus,
)
from app.money import convert, money, round_money
from app.services import audit

ZERO_RATE_TOLERANCE_CENTS = 1


@dataclass(frozen=True)
class LineDraft:
    """One journal line, before validation."""

    account_code: str
    amount: Decimal
    client_id: str
    holding_id: str | None = None
    currency: str | None = None
    fx_rate: Decimal | None = None
    base_amount: Decimal | None = None
    description: str = ""

    @property
    def is_empty(self) -> bool:
        return self.amount == 0 and (self.base_amount is None or self.base_amount == 0)


@dataclass(frozen=True)
class PricedLine:
    """A journal line once its currency, rate and base amount are settled."""

    account_code: str
    amount: Decimal
    client_id: str
    currency: str
    fx_rate: Decimal
    base_amount: Decimal
    holding_id: str | None = None
    description: str = ""


@dataclass
class PostingContext:
    """Everything a set of posting rules needs in order to resolve its roles."""

    client: Client
    custody_account: CustodyAccount | None = None
    target_custody_account: CustodyAccount | None = None
    holding: Holding | None = None
    descriptions: dict[str, str] = field(default_factory=dict)

    @property
    def asset_class(self) -> AssetClass | None:
        return self.holding.asset_class if self.holding is not None else None


def build_lines(
    db: Session,
    ctx: PostingContext,
    rule_key: str,
    amounts: Mapping[str, Decimal],
) -> list[LineDraft]:
    """Turn a rule key plus a dict of amounts into journal lines.

    Zero-amount lines are skipped.  A required line whose amount is missing is an
    error -- a rule that says the bank must be debited cannot quietly post nothing.
    """
    drafts: list[LineDraft] = []
    for rule in rules_for(rule_key):
        if rule.amount_key not in amounts:
            if rule.required:
                raise BusinessRule(
                    f"posting rule {rule_key} requires amount {rule.amount_key!r}",
                    rule_key=rule_key,
                    amount_key=rule.amount_key,
                )
            continue
        value = money(amounts[rule.amount_key])
        if value == 0:
            continue
        if value < 0:
            raise BusinessRule(
                f"amount {rule.amount_key!r} must not be negative; "
                "the posting rule decides the side",
                rule_key=rule_key,
                amount_key=rule.amount_key,
                value=str(value),
            )
        custody = ctx.custody_account
        if rule.role is Role.BANK_TO:
            custody = ctx.target_custody_account
        code = resolve(
            db,
            ctx.client.id,
            rule.role,
            custody_account=custody,
            asset_class=ctx.asset_class,
        )
        currency = None
        if rule.role is Role.BANK_TO and ctx.target_custody_account is not None:
            currency = ctx.target_custody_account.currency
        drafts.append(
            LineDraft(
                account_code=code,
                amount=value * rule.sign,
                client_id=ctx.client.id,
                holding_id=ctx.holding.id if ctx.holding is not None else None,
                currency=currency,
                description=ctx.descriptions.get(rule.amount_key, ""),
            )
        )
    return drafts


def post(
    db: Session,
    *,
    entry_date: date,
    event: LedgerEvent,
    client_id: str,
    currency: str,
    lines: list[LineDraft],
    narrative: str = "",
    reference: str | None = None,
    instruction_id: int | None = None,
    reverses_id: int | None = None,
    batch_id: int | None = None,
    created_by: str,
    multi_currency: bool = False,
    allow_fx_difference: bool = False,
    bypass_period_lock: bool = False,
) -> JournalEntry:
    """Validate and write one journal entry.  Raises on any rule failure."""

    # --- 1. client, and at least two lines that actually move something ------
    client = db.get(Client, client_id)
    if client is None:
        raise NotFound(f"unknown client {client_id}", client_id=client_id)
    if client.status is RecordStatus.CLOSED:
        raise BusinessRule(f"client {client_id} is closed", client_id=client_id)

    drafts = [draft for draft in lines if not draft.is_empty]
    if len(drafts) < 2:
        raise UnbalancedEntry(
            "a journal entry needs at least two lines that move a non-zero amount",
            lines=len(drafts),
            event=str(event),
        )

    base_currency = client.base_currency

    # --- 2. currency, rate and base amount per line --------------------------
    priced: list[PricedLine] = []
    for draft in drafts:
        line_currency = draft.currency or currency
        line_rate = draft.fx_rate
        if line_rate is None:
            line_rate = fx.rate_for(db, line_currency, base_currency, entry_date)
        base = (
            draft.base_amount if draft.base_amount is not None else convert(draft.amount, line_rate)
        )
        priced.append(
            PricedLine(
                account_code=draft.account_code,
                amount=money(draft.amount),
                client_id=draft.client_id,
                currency=line_currency,
                fx_rate=line_rate,
                base_amount=money(base),
                holding_id=draft.holding_id,
                description=draft.description,
            )
        )

    # --- 3. the entry must balance -------------------------------------------
    currencies = {line.currency for line in priced}
    single_currency = currencies == {currency}
    if not single_currency and not multi_currency:
        raise UnbalancedEntry(
            "this entry mixes currencies; only FX entries may do that",
            entry_currency=currency,
            line_currencies=sorted(c for c in currencies if c),
        )

    if single_currency:
        own = sum((line.amount for line in priced), Decimal(0))
        if own != 0:
            raise UnbalancedEntry(
                f"lines do not sum to zero in {currency}: {own:+.2f}",
                currency=currency,
                difference=f"{own:.2f}",
            )

    base_sum = sum((line.base_amount for line in priced), Decimal(0))
    if base_sum != 0:
        priced = _settle_base_difference(
            db,
            priced,
            base_sum=money(base_sum),
            client=client,
            single_currency=single_currency,
            allow_fx_difference=allow_fx_difference,
        )

    # --- 4. the period must be open ------------------------------------------
    if not bypass_period_lock:
        lock = db.get(PeriodLock, client_id)
        if lock is not None and entry_date <= lock.locked_through:
            raise PeriodLocked(
                f"{client_id} is closed through {lock.locked_through.isoformat()}; "
                f"cannot post on {entry_date.isoformat()}",
                client_id=client_id,
                locked_through=lock.locked_through.isoformat(),
                entry_date=entry_date.isoformat(),
            )

    # --- 5. accounts ---------------------------------------------------------
    codes = sorted({line.account_code for line in priced})
    accounts = {
        acc.code: acc
        for acc in db.execute(select(Account).where(Account.code.in_(codes))).scalars()
    }
    for code in codes:
        account = accounts.get(code)
        if account is None:
            raise NotFound(f"unknown account {code}", account_code=code)
        if not account.is_postable:
            raise AccountNotPostable(
                f"account {code} ({account.name}) is a heading and cannot be posted to",
                account_code=code,
            )
        if account.status is not RecordStatus.ACTIVE:
            raise AccountNotPostable(
                f"account {code} ({account.name}) is {account.status}",
                account_code=code,
                status=str(account.status),
            )
        if account.type is AccountType.EQUITY:
            raise SegregationBreach(
                f"account {code} is firm equity; client money is always a liability",
                account_code=code,
            )

    for line in priced:
        account = accounts[line.account_code]
        if account.needs_holding and not line.holding_id:
            raise HoldingRequired(
                f"account {line.account_code} ({account.name}) is a sub-ledger account "
                "and needs a holding",
                account_code=line.account_code,
            )
        if account.currency and line.currency != account.currency:
            raise BusinessRule(
                f"account {line.account_code} is a {account.currency} account; "
                f"line is {line.currency}",
                account_code=line.account_code,
                account_currency=account.currency,
                line_currency=line.currency,
            )

    # --- 6. segregation ------------------------------------------------------
    owners = client_owned_accounts(db)
    for line in priced:
        owner = owners.get(line.account_code)
        if owner is not None and owner != line.client_id:
            raise SegregationBreach(
                f"account {line.account_code} belongs to {owner}; "
                f"it cannot take a line for {line.client_id}",
                account_code=line.account_code,
                owner=owner,
                client_id=line.client_id,
            )
        if line.client_id != client_id:
            raise SegregationBreach(
                f"line for client {line.client_id} inside an entry for {client_id}",
                entry_client=client_id,
                line_client=line.client_id,
            )

    holding_ids = sorted({line.holding_id for line in priced if line.holding_id})
    if holding_ids:
        held = {
            holding.id: holding
            for holding in db.execute(select(Holding).where(Holding.id.in_(holding_ids))).scalars()
        }
        for holding_id in holding_ids:
            holding = held.get(holding_id)
            if holding is None:
                raise NotFound(f"unknown holding {holding_id}", holding_id=holding_id)
            if holding.client_id != client_id:
                raise SegregationBreach(
                    f"holding {holding_id} belongs to {holding.client_id}, not {client_id}",
                    holding_id=holding_id,
                    owner=holding.client_id,
                    client_id=client_id,
                )

    # --- 7. write entry, lines and the audit row in one transaction ----------
    entry = JournalEntry(
        entry_date=entry_date,
        event=event,
        client_id=client_id,
        currency=currency,
        reference=reference,
        narrative=narrative,
        instruction_id=instruction_id,
        reverses_id=reverses_id,
        batch_id=batch_id,
        created_by=created_by,
    )
    db.add(entry)
    db.flush()

    for line in priced:
        db.add(
            JournalLine(
                entry_id=entry.id,
                account_code=line.account_code,
                client_id=line.client_id,
                holding_id=line.holding_id,
                amount=line.amount,
                currency=line.currency,
                fx_rate=line.fx_rate,
                base_amount=line.base_amount,
                description=line.description,
            )
        )
    db.flush()

    audit.record(
        db,
        user_id=created_by,
        action="LEDGER_POST",
        entity="journal_entry",
        entity_id=entry.id,
        client_id=client_id,
        detail={
            "event": str(event),
            "entry_date": entry_date.isoformat(),
            "currency": currency,
            "reference": reference,
            "lines": [
                {
                    "account_code": line.account_code,
                    "holding_id": line.holding_id,
                    "amount": f"{line.amount:.2f}",
                    "currency": line.currency,
                    "base_amount": f"{line.base_amount:.2f}",
                }
                for line in priced
            ],
        },
    )
    db.refresh(entry)
    return entry


def _settle_base_difference(
    db: Session,
    priced: list[PricedLine],
    *,
    base_sum: Decimal,
    client: Client,
    single_currency: bool,
    allow_fx_difference: bool,
) -> list[PricedLine]:
    """Deal with a base-currency imbalance.

    A single-currency entry can only be out by rounding, and the specification says to
    absorb that cent on the largest line.  A multi-currency entry is out because the
    rates on its two sides differ: that difference is a realised exchange gain when
    the debits exceed the credits in base currency, and a loss otherwise.
    """
    if allow_fx_difference:
        role = Role.FX_GAIN if base_sum > 0 else Role.FX_LOSS
        code = resolve(db, client.id, role)
        return [
            *priced,
            PricedLine(
                account_code=code,
                amount=money(-base_sum),
                client_id=client.id,
                currency=client.base_currency,
                fx_rate=Decimal("1.00000000"),
                base_amount=money(-base_sum),
                description="Exchange difference on conversion",
            ),
        ]

    tolerance = Decimal(len(priced) * ZERO_RATE_TOLERANCE_CENTS) / 100
    if not single_currency or abs(base_sum) > tolerance:
        raise UnbalancedEntry(
            f"base amounts do not sum to zero in {client.base_currency}: {base_sum:+.2f}",
            base_currency=client.base_currency,
            difference=f"{base_sum:.2f}",
        )

    largest = max(range(len(priced)), key=lambda i: abs(priced[i].amount))
    target = priced[largest]
    adjusted = replace(target, base_amount=money(round_money(target.base_amount - base_sum)))
    return [adjusted if i == largest else line for i, line in enumerate(priced)]
