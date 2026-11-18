"""Reports: trial balance, balance sheet, P&L, client statement, portfolio summary.

The client statement is the one that matters most.  Section A is what the client is
owed -- its capital plus the profit attributed to it.  Section B is where that money
actually is -- cash, investments and receivables less payables.  A must equal B; if it
does not, the statement is held rather than sent, and the reason is shown.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import NotFound
from app.ledger import balances
from app.ledger.roles import Role, resolve
from app.models import (
    AccountType,
    AssetClass,
    Client,
    CustodyAccount,
    Holding,
    HoldingStatus,
    Instruction,
    InstructionStatus,
    JournalEntry,
    JournalLine,
    LedgerEvent,
    PeriodLock,
)
from app.money import ZERO, money
from app.services import holdings as holdings_svc
from app.services import reconciliation as recon_svc

FEE_ACCOUNTS = ["5110", "5120", "5130", "5140"]
SUSPENSE_ROLE = Role.SUSPENSE


@dataclass(frozen=True)
class ReportLine:
    code: str
    name: str
    amount: Decimal


@dataclass(frozen=True)
class YourAccount:
    capital_brought_forward: Decimal
    capital_movements: Decimal
    profit_brought_forward: Decimal
    profit_earned_closed: Decimal
    profit_paid: Decimal
    profit_open_period: Decimal
    fees_charged: Decimal
    profit_other_movements: Decimal
    your_balance: Decimal


@dataclass(frozen=True)
class WhereHeld:
    assets: list[ReportLine]
    less_payables: list[ReportLine]
    net_holdings: Decimal


@dataclass(frozen=True)
class StatementHolding:
    id: str
    asset_class: str
    currency: str
    outstanding: Decimal
    accrued_profit: Decimal
    fair_value_adjustment: Decimal
    profit_rate: Decimal | None
    maturity_date: date | None
    status: str


@dataclass(frozen=True)
class Statement:
    client: str
    client_id: str
    currency: str
    from_date: date
    to_date: date
    your_account: YourAccount
    where_held: WhereHeld
    holdings: list[StatementHolding]
    reconciles: bool
    held_reason: str | None


def _client(db: Session, client_id: str) -> Client:
    client = db.get(Client, client_id)
    if client is None:
        raise NotFound(f"unknown client {client_id}", client_id=client_id)
    return client


# --- Trial balance, balance sheet, P&L ---------------------------------------


@dataclass(frozen=True)
class TrialBalanceRow:
    code: str
    name: str
    type: str
    debit: Decimal
    credit: Decimal


@dataclass(frozen=True)
class TrialBalance:
    as_of: date
    client_id: str | None
    rows: list[TrialBalanceRow]

    @property
    def total_debit(self) -> Decimal:
        return money(sum((row.debit for row in self.rows), Decimal(0)))

    @property
    def total_credit(self) -> Decimal:
        return money(sum((row.credit for row in self.rows), Decimal(0)))

    @property
    def balanced(self) -> bool:
        return self.total_debit == self.total_credit


def trial_balance(db: Session, *, as_of: date, client_id: str | None = None) -> TrialBalance:
    rows = [
        TrialBalanceRow(
            code=row.account_code,
            name=row.name,
            type=str(row.type),
            debit=row.base_amount if row.base_amount > 0 else ZERO,
            credit=-row.base_amount if row.base_amount < 0 else ZERO,
        )
        for row in balances.by_account(db, client_id=client_id, as_of=as_of)
    ]
    return TrialBalance(as_of=as_of, client_id=client_id, rows=rows)


@dataclass(frozen=True)
class SectionTotal:
    label: str
    lines: list[ReportLine]
    total: Decimal


@dataclass(frozen=True)
class BalanceSheet:
    client_id: str
    client: str
    currency: str
    as_of: date
    assets: SectionTotal
    liabilities: SectionTotal
    client_funds: SectionTotal
    retained_result: Decimal


def balance_sheet(db: Session, client_id: str, *, as_of: date) -> BalanceSheet:
    client = _client(db, client_id)
    capital = resolve(db, client_id, Role.CLIENT_CAPITAL)
    profit = resolve(db, client_id, Role.CLIENT_PROFIT)

    asset_lines: list[ReportLine] = []
    liability_lines: list[ReportLine] = []
    fund_lines: list[ReportLine] = []
    for row in balances.by_account(db, client_id=client_id, as_of=as_of):
        line = ReportLine(code=row.account_code, name=row.name, amount=row.presented)
        if row.type is AccountType.ASSET:
            asset_lines.append(line)
        elif row.type is AccountType.LIABILITY:
            (fund_lines if row.account_code in (capital, profit) else liability_lines).append(line)

    open_result = (
        -balances.balance(
            db,
            client_id=client_id,
            as_of=as_of,
            base=True,
            account_codes=_pl_codes(db, client_id, as_of),
        )
        if _pl_codes(db, client_id, as_of)
        else ZERO
    )

    return BalanceSheet(
        client_id=client_id,
        client=client.legal_name,
        currency=client.base_currency,
        as_of=as_of,
        assets=SectionTotal("Assets", asset_lines, _total(asset_lines)),
        liabilities=SectionTotal("Liabilities", liability_lines, _total(liability_lines)),
        client_funds=SectionTotal("Client funds", fund_lines, _total(fund_lines)),
        retained_result=open_result,
    )


def _total(lines: list[ReportLine]) -> Decimal:
    return money(sum((line.amount for line in lines), Decimal(0)))


def _pl_codes(db: Session, client_id: str, as_of: date) -> list[str]:
    return [
        row.account_code
        for row in balances.by_account(
            db,
            client_id=client_id,
            as_of=as_of,
            types=(AccountType.INCOME, AccountType.EXPENSE),
        )
    ]


@dataclass(frozen=True)
class ProfitAndLoss:
    client_id: str
    client: str
    currency: str
    from_date: date
    to_date: date
    income: SectionTotal
    expenses: SectionTotal

    @property
    def net_profit(self) -> Decimal:
        return money(self.income.total - self.expenses.total)


def profit_and_loss(
    db: Session, client_id: str, *, from_date: date, to_date: date
) -> ProfitAndLoss:
    """Income and costs for the period.

    Close entries are excluded so the report still shows what the period earned, even
    after the result has been moved to the client.
    """
    client = _client(db, client_id)
    income: list[ReportLine] = []
    expenses: list[ReportLine] = []
    for row in balances.by_account(
        db,
        client_id=client_id,
        from_date=from_date,
        as_of=to_date,
        types=(AccountType.INCOME, AccountType.EXPENSE),
        exclude_events=(LedgerEvent.MONTH_END_CLOSE,),
    ):
        line = ReportLine(code=row.account_code, name=row.name, amount=row.presented)
        (income if row.type is AccountType.INCOME else expenses).append(line)
    return ProfitAndLoss(
        client_id=client_id,
        client=client.legal_name,
        currency=client.base_currency,
        from_date=from_date,
        to_date=to_date,
        income=SectionTotal("Income", income, _total(income)),
        expenses=SectionTotal("Expenses", expenses, _total(expenses)),
    )


# --- Client statement --------------------------------------------------------

_CLOSED = (LedgerEvent.MONTH_END_CLOSE,)
_PAID = (LedgerEvent.PROFIT_PAID_TO_CLIENT,)
_OPENING = (LedgerEvent.OPENING_BALANCE,)


def client_statement(db: Session, client_id: str, *, from_date: date, to_date: date) -> Statement:
    client = _client(db, client_id)
    capital_code = resolve(db, client_id, Role.CLIENT_CAPITAL)
    profit_code = resolve(db, client_id, Role.CLIENT_PROFIT)
    prior = from_date - timedelta(days=1)

    def owed(code: str, **kwargs: object) -> Decimal:
        return -balances.balance(db, client_id=client_id, account_code=code, base=True, **kwargs)  # type: ignore[arg-type]

    capital_bf = money(
        owed(capital_code, as_of=prior)
        + owed(capital_code, from_date=from_date, as_of=to_date, only_events=_OPENING)
    )
    capital_movements = owed(
        capital_code, from_date=from_date, as_of=to_date, exclude_events=_OPENING
    )
    profit_bf = money(
        owed(profit_code, as_of=prior)
        + owed(profit_code, from_date=from_date, as_of=to_date, only_events=_OPENING)
    )
    profit_earned_closed = owed(
        profit_code, from_date=from_date, as_of=to_date, only_events=_CLOSED
    )
    profit_paid = -owed(profit_code, from_date=from_date, as_of=to_date, only_events=_PAID)
    profit_other = owed(
        profit_code,
        from_date=from_date,
        as_of=to_date,
        exclude_events=_OPENING + _CLOSED + _PAID,
    )

    pl_codes = _pl_codes(db, client_id, to_date)
    profit_open_period = (
        -balances.balance(db, client_id=client_id, as_of=to_date, base=True, account_codes=pl_codes)
        if pl_codes
        else ZERO
    )
    fees_charged = balances.balance(
        db,
        client_id=client_id,
        account_codes=FEE_ACCOUNTS,
        from_date=from_date,
        as_of=to_date,
        base=True,
        exclude_events=_CLOSED,
    )

    your_balance = money(
        capital_bf
        + capital_movements
        + profit_bf
        + profit_earned_closed
        - profit_paid
        + profit_other
        + profit_open_period
    )

    assets: list[ReportLine] = []
    payables: list[ReportLine] = []
    for row in balances.by_account(db, client_id=client_id, as_of=to_date):
        if row.type is AccountType.ASSET:
            assets.append(ReportLine(row.account_code, row.name, row.presented))
        elif row.type is AccountType.LIABILITY and row.account_code not in (
            capital_code,
            profit_code,
        ):
            payables.append(ReportLine(row.account_code, row.name, row.presented))
    net_holdings = money(_total(assets) - _total(payables))

    statement_holdings = [
        StatementHolding(
            id=summary.holding.id,
            asset_class=str(summary.holding.asset_class),
            currency=summary.holding.currency,
            outstanding=summary.outstanding,
            accrued_profit=summary.accrued_profit,
            fair_value_adjustment=summary.fair_value_adjustment,
            profit_rate=summary.holding.profit_rate,
            maturity_date=summary.holding.maturity_date,
            status=str(summary.holding.status),
        )
        for summary in (
            holdings_svc.summarise(db, holding, to_date)
            for holding in holdings_svc.client_holdings(db, client_id)
        )
        if summary.outstanding != 0
        or summary.accrued_profit != 0
        or summary.holding.status is HoldingStatus.ACTIVE
    ]

    reconciles = your_balance == net_holdings
    held_reason = None
    if not reconciles:
        held_reason = (
            f"Section A of {your_balance:.2f} does not equal Section B of "
            f"{net_holdings:.2f}; the statement is held pending investigation"
        )
    else:
        suspense = balances.balance(
            db,
            client_id=client_id,
            account_code=resolve(db, client_id, SUSPENSE_ROLE),
            as_of=to_date,
            base=True,
        )
        if suspense != 0:
            held_reason = (
                f"{suspense:.2f} is sitting in suspense, unreconciled at cutover and under "
                "finance review; statements are held until a correcting entry clears it"
            )

    return Statement(
        client=client.legal_name,
        client_id=client_id,
        currency=client.base_currency,
        from_date=from_date,
        to_date=to_date,
        your_account=YourAccount(
            capital_brought_forward=capital_bf,
            capital_movements=capital_movements,
            profit_brought_forward=profit_bf,
            profit_earned_closed=profit_earned_closed,
            profit_paid=profit_paid,
            profit_open_period=profit_open_period,
            fees_charged=fees_charged,
            profit_other_movements=profit_other,
            your_balance=your_balance,
        ),
        where_held=WhereHeld(assets=assets, less_payables=payables, net_holdings=net_holdings),
        holdings=statement_holdings,
        reconciles=reconciles,
        held_reason=held_reason,
    )


# --- Portfolio summary (CMA Licensing Regs 2025, reg 40(1)) ------------------


@dataclass(frozen=True)
class PortfolioRow:
    client_id: str
    client: str
    asset_class: str
    count: int
    cost: Decimal
    fair_value: Decimal
    accrued_profit: Decimal


@dataclass(frozen=True)
class PortfolioCash:
    client_id: str
    custodian: str
    account_number: str
    currency: str
    balance: Decimal
    base_amount: Decimal


@dataclass(frozen=True)
class PortfolioSummary:
    as_of: date
    number_of_clients: int
    rows: list[PortfolioRow]
    cash: list[PortfolioCash]
    totals: dict[str, Decimal] = field(default_factory=dict)


def portfolio_summary(
    db: Session, *, as_of: date, client_id: str | None = None
) -> PortfolioSummary:
    client_ids = (
        [client_id]
        if client_id
        else list(db.execute(select(Client.id).order_by(Client.id)).scalars())
    )
    rows: list[PortfolioRow] = []
    cash: list[PortfolioCash] = []
    aum = ZERO

    for cid in client_ids:
        client = _client(db, cid)
        grouped: dict[AssetClass, list[holdings_svc.HoldingSummary]] = {}
        for holding in holdings_svc.client_holdings(db, cid):
            summary = holdings_svc.summarise(db, holding, as_of)
            if summary.outstanding == 0 and summary.accrued_profit == 0:
                continue
            grouped.setdefault(holding.asset_class, []).append(summary)

        for asset_class, items in sorted(grouped.items(), key=lambda kv: str(kv[0])):
            rate = _base_rate(db, items[0].holding.currency, client.base_currency, as_of)
            cost = money(sum((item.outstanding for item in items), Decimal(0)) * rate)
            fair = money(sum((item.fair_value for item in items), Decimal(0)) * rate)
            accrued = money(sum((item.accrued_profit for item in items), Decimal(0)) * rate)
            aum = money(aum + fair + accrued)
            rows.append(
                PortfolioRow(
                    client_id=cid,
                    client=client.legal_name,
                    asset_class=str(asset_class),
                    count=len(items),
                    cost=cost,
                    fair_value=fair,
                    accrued_profit=accrued,
                )
            )

        for account in db.execute(
            select(CustodyAccount)
            .where(CustodyAccount.client_id == cid)
            .order_by(CustodyAccount.id)
        ).scalars():
            own = balances.balance(
                db,
                client_id=cid,
                account_code=account.cash_ledger_code,
                currency=account.currency,
                as_of=as_of,
            )
            base = balances.balance(
                db,
                client_id=cid,
                account_code=account.cash_ledger_code,
                currency=account.currency,
                as_of=as_of,
                base=True,
            )
            if own == 0 and base == 0:
                continue
            aum = money(aum + base)
            cash.append(
                PortfolioCash(
                    client_id=cid,
                    custodian=account.custodian,
                    account_number=account.account_number,
                    currency=account.currency,
                    balance=own,
                    base_amount=base,
                )
            )

    return PortfolioSummary(
        as_of=as_of,
        number_of_clients=len(client_ids),
        rows=rows,
        cash=cash,
        totals={"assets_under_management": aum},
    )


def _base_rate(db: Session, currency: str, base_currency: str, as_of: date) -> Decimal:
    from app.ledger import fx as fx_rates

    return fx_rates.rate_for(db, currency, base_currency, as_of)


# --- Dashboard ---------------------------------------------------------------


@dataclass(frozen=True)
class DashboardClient:
    client_id: str
    client: str
    currency: str
    net_asset_value: Decimal
    reconciles: bool
    held_reason: str | None
    suspense: Decimal
    locked_through: date | None
    kyc_status: str


@dataclass(frozen=True)
class MaturityRow:
    holding_id: str
    client_id: str
    counterparty: str
    currency: str
    outstanding: Decimal
    maturity_date: date
    days: int


@dataclass(frozen=True)
class Dashboard:
    as_of: date
    clients: list[DashboardClient]
    aum_by_asset_class: dict[str, Decimal]
    awaiting_my_action: list[dict[str, object]]
    reconciliation_breaks: list[str]
    maturities_30: list[MaturityRow]
    maturities_90: list[MaturityRow]
    suspense_total: Decimal
    instructions_in_progress: list[dict[str, object]]


def dashboard(db: Session, *, as_of: date, user_id: str | None = None) -> Dashboard:
    from app.models import User
    from app.services import instructions as ins_svc

    client_rows: list[DashboardClient] = []
    aum: dict[str, Decimal] = {}
    breaks: list[str] = []
    suspense_total = ZERO

    for cid in db.execute(select(Client.id).order_by(Client.id)).scalars():
        client = _client(db, cid)
        statement = client_statement(db, cid, from_date=date(1900, 1, 1), to_date=as_of)
        lock = db.get(PeriodLock, cid)
        suspense = balances.balance(
            db,
            client_id=cid,
            account_code=resolve(db, cid, SUSPENSE_ROLE),
            as_of=as_of,
            base=True,
        )
        suspense_total = money(suspense_total + suspense)
        client_rows.append(
            DashboardClient(
                client_id=cid,
                client=client.legal_name,
                currency=client.base_currency,
                net_asset_value=statement.where_held.net_holdings,
                reconciles=statement.reconciles,
                held_reason=statement.held_reason,
                suspense=suspense,
                locked_through=lock.locked_through if lock else None,
                kyc_status=str(client.kyc_status),
            )
        )
        breaks.extend(f"{cid}: {item}" for item in recon_svc.breaks_at(db, cid, as_of))

    summary = portfolio_summary(db, as_of=as_of)
    for row in summary.rows:
        aum[row.asset_class] = money(aum.get(row.asset_class, ZERO) + row.fair_value)
    cash_total = money(sum((row.base_amount for row in summary.cash), Decimal(0)))
    if cash_total != 0:
        aum["CASH"] = cash_total

    awaiting: list[dict[str, object]] = []
    if user_id is not None:
        user = db.get(User, user_id)
        if user is not None:
            awaiting = [
                {
                    "id": item.id,
                    "reference": item.reference,
                    "client_id": item.client_id,
                    "type": str(item.type),
                    "amount": f"{item.amount:.2f}",
                    "currency": item.currency,
                    "status": str(item.status),
                    "value_date": item.value_date.isoformat(),
                }
                for item in ins_svc.awaiting(db, user)
            ]

    in_progress = [
        {
            "id": item.id,
            "reference": item.reference,
            "client_id": item.client_id,
            "type": str(item.type),
            "amount": f"{item.amount:.2f}",
            "currency": item.currency,
            "status": str(item.status),
            "value_date": item.value_date.isoformat(),
            "approvals": len(item.approvals),
        }
        for item in db.execute(
            select(Instruction)
            .where(
                Instruction.status.in_(
                    [
                        InstructionStatus.PENDING_APPROVAL,
                        InstructionStatus.APPROVED,
                        InstructionStatus.SENT,
                    ]
                )
            )
            .order_by(Instruction.value_date, Instruction.id)
        ).scalars()
    ]

    maturities = _maturities(db, as_of)
    return Dashboard(
        as_of=as_of,
        clients=client_rows,
        aum_by_asset_class=aum,
        awaiting_my_action=awaiting,
        reconciliation_breaks=breaks,
        maturities_30=[row for row in maturities if row.days <= 30],
        maturities_90=maturities,
        suspense_total=suspense_total,
        instructions_in_progress=in_progress,
    )


def _maturities(db: Session, as_of: date) -> list[MaturityRow]:
    horizon = as_of + timedelta(days=90)
    rows: list[MaturityRow] = []
    for holding in db.execute(
        select(Holding)
        .where(
            Holding.status == HoldingStatus.ACTIVE,
            Holding.maturity_date.is_not(None),
            Holding.maturity_date <= horizon,
            Holding.maturity_date >= as_of,
        )
        .order_by(Holding.maturity_date)
    ).scalars():
        assert holding.maturity_date is not None
        outstanding = holdings_svc.outstanding(db, holding, as_of)
        if outstanding == 0:
            continue
        rows.append(
            MaturityRow(
                holding_id=holding.id,
                client_id=holding.client_id,
                counterparty=holding.counterparty,
                currency=holding.currency,
                outstanding=outstanding,
                maturity_date=holding.maturity_date,
                days=(holding.maturity_date - as_of).days,
            )
        )
    return rows


def journal_search(
    db: Session,
    *,
    client_id: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    account_code: str | None = None,
    holding_id: str | None = None,
    event: LedgerEvent | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[JournalEntry], int]:
    stmt = select(JournalEntry).order_by(JournalEntry.entry_date.desc(), JournalEntry.id.desc())
    count_stmt = select(func.count()).select_from(JournalEntry)
    if client_id:
        stmt = stmt.where(JournalEntry.client_id == client_id)
        count_stmt = count_stmt.where(JournalEntry.client_id == client_id)
    if from_date:
        stmt = stmt.where(JournalEntry.entry_date >= from_date)
        count_stmt = count_stmt.where(JournalEntry.entry_date >= from_date)
    if to_date:
        stmt = stmt.where(JournalEntry.entry_date <= to_date)
        count_stmt = count_stmt.where(JournalEntry.entry_date <= to_date)
    if event:
        stmt = stmt.where(JournalEntry.event == event)
        count_stmt = count_stmt.where(JournalEntry.event == event)
    if account_code or holding_id:
        sub = select(JournalLine.entry_id)
        if account_code:
            sub = sub.where(JournalLine.account_code == account_code)
        if holding_id:
            sub = sub.where(JournalLine.holding_id == holding_id)
        stmt = stmt.where(JournalEntry.id.in_(sub))
        count_stmt = count_stmt.where(JournalEntry.id.in_(sub))
    total = db.execute(count_stmt).scalar_one()
    entries = list(db.execute(stmt.limit(limit).offset(offset)).scalars())
    return entries, int(total)
