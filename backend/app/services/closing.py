"""Month-end close.

The order matters and is fixed: accrue, revalue, check the reconciliation, move the
period's result to the client.  Everything happens in one transaction per client, so
a close either completes or leaves the books exactly as they were.

This test system does not lock the period afterwards -- see the module's lack of any
PeriodLock write below -- so a back-dated posting after close remains possible and a
repeated close simply re-sweeps (posting nothing further, since nothing changed).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import BusinessRule, NotFound
from app.ledger import balances
from app.ledger.posting import LineDraft, post
from app.ledger.roles import Role, resolve
from app.models import (
    AccountType,
    ApprovalStatus,
    Client,
    JournalEntry,
    LedgerEvent,
    PeriodLock,
    ReconciliationRun,
    Valuation,
)
from app.money import ZERO, money
from app.services import accruals, audit
from app.services import fx as fx_svc
from app.services import reconciliation as recon_svc


@dataclass
class ChecklistItem:
    key: str
    label: str
    done: bool
    detail: str = ""
    blocking: bool = False


@dataclass
class Checklist:
    client_id: str
    period_end: date
    items: list[ChecklistItem] = field(default_factory=list)

    @property
    def can_close(self) -> bool:
        return not any(item.blocking and not item.done for item in self.items)


@dataclass
class CloseResult:
    client_id: str
    period_end: date
    accrual: accruals.AccrualRun | None
    revaluation: fx_svc.RevaluationResult | None
    entry: JournalEntry | None
    net_profit: Decimal
    locked_through: date
    already_closed: bool = False


def _client(db: Session, client_id: str) -> Client:
    client = db.get(Client, client_id)
    if client is None:
        raise NotFound(f"unknown client {client_id}", client_id=client_id)
    return client


def locked_through(db: Session, client_id: str) -> date | None:
    lock = db.get(PeriodLock, client_id)
    return lock.locked_through if lock is not None else None


def checklist(db: Session, client_id: str, period_end: date) -> Checklist:
    """What still has to happen before this period can be closed."""
    _client(db, client_id)
    lock = locked_through(db, client_id)
    items: list[ChecklistItem] = []

    items.append(
        ChecklistItem(
            key="period_open",
            label="Period is still open",
            done=lock is None or lock < period_end,
            detail=f"locked through {lock.isoformat()}" if lock else "no lock",
            blocking=True,
        )
    )

    accrual_outstanding = _accruals_outstanding(db, client_id, period_end)
    items.append(
        ChecklistItem(
            key="accruals",
            label="Profit, rent and fees accrued to the period end",
            done=not accrual_outstanding,
            detail="; ".join(accrual_outstanding) or "up to date",
        )
    )

    reval = _revaluation_outstanding(db, client_id, period_end)
    items.append(
        ChecklistItem(
            key="fx_revaluation",
            label="Foreign currency balances revalued at closing rates",
            done=not reval,
            detail=reval or "nothing to revalue",
        )
    )

    run = db.execute(
        select(ReconciliationRun)
        .where(ReconciliationRun.as_of == period_end)
        .where((ReconciliationRun.client_id == client_id) | (ReconciliationRun.client_id.is_(None)))
        .order_by(ReconciliationRun.performed_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    items.append(
        ChecklistItem(
            key="reconciliation",
            label="Custodian reconciliation at the period end has no breaks",
            done=run is not None and run.breaks == 0,
            detail=(
                "no reconciliation run for this date"
                if run is None
                else f"{run.breaks} break(s) on run {run.id}"
            ),
            blocking=True,
        )
    )

    outstanding_valuations = (
        db.execute(
            select(Valuation).where(
                Valuation.client_id == client_id,
                Valuation.status == ApprovalStatus.PENDING,
                Valuation.valuation_date <= period_end,
            )
        )
        .scalars()
        .all()
    )
    items.append(
        ChecklistItem(
            key="valuations",
            label="No valuations awaiting approval",
            done=not outstanding_valuations,
            detail=f"{len(outstanding_valuations)} awaiting approval",
        )
    )

    return Checklist(client_id=client_id, period_end=period_end, items=items)


def _accruals_outstanding(db: Session, client_id: str, period_end: date) -> list[str]:
    """Which holdings would move if the accrual ran now, without posting anything."""
    from app.services import holdings as holdings_svc

    pending: list[str] = []
    for holding in holdings_svc.client_holdings(db, client_id):
        if not holdings_svc.is_accruable(holding):
            continue
        target = holdings_svc.accrual_target(db, holding, period_end)
        booked = holdings_svc.income_recognised(db, holding, period_end)
        if target != booked:
            pending.append(f"{holding.id}: {target - booked:+.2f}")
    return pending


def _revaluation_outstanding(db: Session, client_id: str, period_end: date) -> str:
    client = _client(db, client_id)
    rows = [
        row
        for row in balances.by_holding_currency(db, client_id=client_id, as_of=period_end)
        if row.currency != client.base_currency
        and row.type in (AccountType.ASSET, AccountType.LIABILITY)
    ]
    return f"{len(rows)} foreign currency balance(s) to check" if rows else ""


def close(
    db: Session,
    client_id: str,
    period_end: date,
    *,
    created_by: str,
    override_reason: str | None = None,
) -> CloseResult:
    """Close one period for one client."""
    client = _client(db, client_id)
    lock = locked_through(db, client_id)
    if lock is not None and lock >= period_end:
        return CloseResult(
            client_id=client_id,
            period_end=period_end,
            accrual=None,
            revaluation=None,
            entry=None,
            net_profit=ZERO,
            locked_through=lock,
            already_closed=True,
        )

    # 1. accruals, rent and fees to the period end
    accrual = accruals.run(db, client_id, period_end, created_by=created_by)

    # 2. exchange revaluation at the closing rates
    revaluation = fx_svc.revalue(db, client_id, period_end, created_by=created_by)

    # 3. the reconciliation must be clean, or an override must be recorded
    breaks = recon_svc.breaks_at(db, client_id, period_end)
    if breaks:
        if not override_reason:
            raise BusinessRule(
                f"the custodian reconciliation at {period_end.isoformat()} has "
                f"{len(breaks)} break(s); close needs a written override",
                breaks=breaks,
            )
        audit.record(
            db,
            user_id=created_by,
            action="CLOSE_OVERRIDE",
            entity="client",
            entity_id=client_id,
            client_id=client_id,
            detail={
                "period_end": period_end.isoformat(),
                "reason": override_reason,
                "breaks": breaks,
            },
        )

    # 4. move the period's result to the client
    entry, net_profit = _post_close_entry(db, client, period_end=period_end, created_by=created_by)

    db.flush()

    audit.record(
        db,
        user_id=created_by,
        action="PERIOD_CLOSED",
        entity="client",
        entity_id=client_id,
        client_id=client_id,
        detail={
            "period_end": period_end.isoformat(),
            "net_profit": f"{net_profit:.2f}",
            "journal_entry_id": entry.id if entry else None,
            "profit_accrued": f"{accrual.profit_posted:.2f}",
            "fees_accrued": f"{accrual.fee_posted:.2f}",
            "fx_net": f"{revaluation.net:.2f}",
            "override_reason": override_reason,
        },
    )
    return CloseResult(
        client_id=client_id,
        period_end=period_end,
        accrual=accrual,
        revaluation=revaluation,
        entry=entry,
        net_profit=net_profit,
        locked_through=period_end,
    )


def _post_close_entry(
    db: Session, client: Client, *, period_end: date, created_by: str
) -> tuple[JournalEntry | None, Decimal]:
    """Reverse every P&L base balance and put the net on the client's profit account."""
    rows = balances.by_account(
        db,
        client_id=client.id,
        as_of=period_end,
        types=(AccountType.INCOME, AccountType.EXPENSE),
    )
    rows = [row for row in rows if row.base_amount != 0]
    if not rows:
        return None, ZERO

    total = money(sum((row.base_amount for row in rows), Decimal(0)))
    net_profit = money(-total)

    lines = [
        LineDraft(
            account_code=row.account_code,
            amount=money(-row.base_amount),
            client_id=client.id,
            currency=client.base_currency,
            fx_rate=Decimal("1.00000000"),
            base_amount=money(-row.base_amount),
            description=f"Closed to client profit at {period_end.isoformat()}",
        )
        for row in rows
    ]
    lines.append(
        LineDraft(
            account_code=resolve(db, client.id, Role.CLIENT_PROFIT),
            amount=total,
            client_id=client.id,
            currency=client.base_currency,
            fx_rate=Decimal("1.00000000"),
            base_amount=total,
            description=(
                f"Net {'profit' if net_profit >= 0 else 'loss'} for the period to "
                f"{period_end.isoformat()}"
            ),
        )
    )

    entry = post(
        db,
        entry_date=period_end,
        event=LedgerEvent.MONTH_END_CLOSE,
        client_id=client.id,
        currency=client.base_currency,
        lines=lines,
        narrative=f"Month-end close to {period_end.isoformat()}",
        created_by=created_by,
    )
    return entry, net_profit
