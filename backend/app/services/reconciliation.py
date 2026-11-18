"""Reconciliation against the custodians' own records.

CoB reg 29(5)-(7) requires a daily reconciliation of client cash and reg 31(3)-(4) a
monthly reconciliation of client assets, and neither may be performed by the person
who authorises payments.  The permission table bars signatories; this module records
who ran each reconciliation and every line it compared.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import BusinessRule, NotFound
from app.ledger import balances
from app.models import (
    AssetClass,
    Client,
    CustodianBalance,
    CustodianPosition,
    CustodyAccount,
    Holding,
    HoldingStatus,
    ReconciliationRun,
    RecordStatus,
    utcnow,
)
from app.money import ZERO, money
from app.services import audit
from app.services import holdings as holdings_svc


@dataclass
class ReconLine:
    scope: str
    key: str
    label: str
    currency: str
    ledger: str
    custodian: str | None
    difference: str
    matched: bool
    note: str = ""


@dataclass
class ReconResult:
    as_of: date
    client_id: str | None
    lines: list[ReconLine]
    run_id: int | None = None

    @property
    def breaks(self) -> list[ReconLine]:
        return [line for line in self.lines if not line.matched]


def record_balance(
    db: Session,
    *,
    custody_account_id: str,
    as_of: date,
    balance: Decimal,
    statement_ref: str,
    recorded_by: str,
    source_file_id: int | None = None,
) -> CustodianBalance:
    account = db.get(CustodyAccount, custody_account_id)
    if account is None:
        raise NotFound(
            f"unknown custody account {custody_account_id}",
            custody_account_id=custody_account_id,
        )
    existing = db.execute(
        select(CustodianBalance).where(
            CustodianBalance.custody_account_id == custody_account_id,
            CustodianBalance.as_of == as_of,
        )
    ).scalar_one_or_none()
    row = existing or CustodianBalance(
        custody_account_id=custody_account_id, as_of=as_of, created_by=recorded_by
    )
    row.balance = money(balance)
    row.statement_ref = statement_ref
    row.source_file_id = source_file_id
    db.add(row)
    db.flush()
    audit.record(
        db,
        user_id=recorded_by,
        action="CUSTODIAN_BALANCE_RECORDED",
        entity="custodian_balance",
        entity_id=row.id,
        client_id=account.client_id,
        detail={
            "custody_account_id": custody_account_id,
            "as_of": as_of.isoformat(),
            "balance": f"{row.balance:.2f}",
            "statement_ref": statement_ref,
        },
    )
    return row


def record_position(
    db: Session,
    *,
    holding_id: str,
    as_of: date,
    amount: Decimal,
    statement_ref: str,
    recorded_by: str,
    source_file_id: int | None = None,
) -> CustodianPosition:
    holding = holdings_svc.get_holding(db, holding_id)
    existing = db.execute(
        select(CustodianPosition).where(
            CustodianPosition.holding_id == holding_id, CustodianPosition.as_of == as_of
        )
    ).scalar_one_or_none()
    row = existing or CustodianPosition(holding_id=holding_id, as_of=as_of, created_by=recorded_by)
    row.amount = money(amount)
    row.statement_ref = statement_ref
    row.source_file_id = source_file_id
    db.add(row)
    db.flush()
    audit.record(
        db,
        user_id=recorded_by,
        action="CUSTODIAN_POSITION_RECORDED",
        entity="custodian_position",
        entity_id=row.id,
        client_id=holding.client_id,
        detail={
            "holding_id": holding_id,
            "as_of": as_of.isoformat(),
            "amount": f"{row.amount:.2f}",
            "statement_ref": statement_ref,
        },
    )
    return row


def custodian_position_amount(db: Session, holding: Holding) -> Decimal:
    """What the custodian should be reporting: nominal for Sukuk, principal otherwise."""
    if holding.asset_class is AssetClass.SUKUK and holding.nominal is not None:
        return holding.nominal
    return ZERO


def compare(
    db: Session, *, as_of: date, client_id: str | None = None, scope: str = "BOTH"
) -> ReconResult:
    """Compare the ledger with the custodians' records without writing a run row."""
    client_ids = (
        [client_id]
        if client_id
        else list(db.execute(select(Client.id).order_by(Client.id)).scalars())
    )
    lines: list[ReconLine] = []

    for cid in client_ids:
        if scope in ("CASH", "BOTH"):
            for account in db.execute(
                select(CustodyAccount)
                .where(
                    CustodyAccount.client_id == cid, CustodyAccount.status == RecordStatus.ACTIVE
                )
                .order_by(CustodyAccount.id)
            ).scalars():
                ledger = balances.balance(
                    db,
                    client_id=cid,
                    account_code=account.cash_ledger_code,
                    currency=account.currency,
                    as_of=as_of,
                )
                statement = db.execute(
                    select(CustodianBalance).where(
                        CustodianBalance.custody_account_id == account.id,
                        CustodianBalance.as_of == as_of,
                    )
                ).scalar_one_or_none()
                if statement is None:
                    if ledger == 0:
                        continue
                    lines.append(
                        ReconLine(
                            scope="CASH",
                            key=account.id,
                            label=f"{account.custodian} {account.account_number}",
                            currency=account.currency,
                            ledger=f"{ledger:.2f}",
                            custodian=None,
                            difference=f"{ledger:.2f}",
                            matched=False,
                            note="no custodian statement on file for this date",
                        )
                    )
                    continue
                difference = money(ledger - statement.balance)
                lines.append(
                    ReconLine(
                        scope="CASH",
                        key=account.id,
                        label=f"{account.custodian} {account.account_number}",
                        currency=account.currency,
                        ledger=f"{ledger:.2f}",
                        custodian=f"{statement.balance:.2f}",
                        difference=f"{difference:.2f}",
                        matched=difference == 0,
                        note=statement.statement_ref,
                    )
                )

        if scope in ("POSITIONS", "BOTH"):
            for holding in holdings_svc.client_holdings(db, cid, status=HoldingStatus.ACTIVE):
                ledger = holdings_svc.outstanding(db, holding, as_of)
                expected = (
                    holding.nominal
                    if holding.asset_class is AssetClass.SUKUK and holding.nominal is not None
                    else ledger
                )
                position = db.execute(
                    select(CustodianPosition).where(
                        CustodianPosition.holding_id == holding.id,
                        CustodianPosition.as_of == as_of,
                    )
                ).scalar_one_or_none()
                if position is None:
                    if ledger == 0:
                        continue
                    lines.append(
                        ReconLine(
                            scope="POSITION",
                            key=holding.id,
                            label=f"{holding.counterparty} {holding.id}",
                            currency=holding.currency,
                            ledger=f"{expected:.2f}",
                            custodian=None,
                            difference=f"{expected:.2f}",
                            matched=False,
                            note="no custodian position report on file for this date",
                        )
                    )
                    continue
                difference = money(expected - position.amount)
                lines.append(
                    ReconLine(
                        scope="POSITION",
                        key=holding.id,
                        label=f"{holding.counterparty} {holding.id}",
                        currency=holding.currency,
                        ledger=f"{expected:.2f}",
                        custodian=f"{position.amount:.2f}",
                        difference=f"{difference:.2f}",
                        matched=difference == 0,
                        note=position.statement_ref,
                    )
                )

    return ReconResult(as_of=as_of, client_id=client_id, lines=lines)


def run(
    db: Session,
    *,
    as_of: date,
    performed_by: str,
    client_id: str | None = None,
    scope: str = "BOTH",
) -> ReconResult:
    """Run and record a reconciliation.  Breaks stay visible until they clear."""
    if scope not in ("CASH", "POSITIONS", "BOTH"):
        raise BusinessRule(f"unknown reconciliation scope {scope!r}", scope=scope)
    result = compare(db, as_of=as_of, client_id=client_id, scope=scope)
    payload: dict[str, Any] = {"lines": [asdict(line) for line in result.lines]}
    row = ReconciliationRun(
        client_id=client_id,
        as_of=as_of,
        scope=scope,
        performed_by=performed_by,
        performed_at=utcnow(),
        breaks=len(result.breaks),
        result=payload,
        created_by=performed_by,
    )
    db.add(row)
    db.flush()
    audit.record(
        db,
        user_id=performed_by,
        action="RECONCILIATION_RUN",
        entity="reconciliation_run",
        entity_id=row.id,
        client_id=client_id,
        detail={"as_of": as_of.isoformat(), "scope": scope, "breaks": row.breaks},
    )
    result.run_id = row.id
    return result


def breaks_at(db: Session, client_id: str, as_of: date) -> list[str]:
    """Unresolved breaks for the close checklist, recomputed live from the ledger."""
    result = compare(db, as_of=as_of, client_id=client_id, scope="BOTH")
    return [
        f"{line.scope} {line.key}: ledger {line.ledger} vs custodian "
        f"{line.custodian or 'none'} ({line.note})"
        for line in result.breaks
    ]


def latest_runs(db: Session, *, limit: int = 20) -> list[ReconciliationRun]:
    return list(
        db.execute(
            select(ReconciliationRun).order_by(ReconciliationRun.performed_at.desc()).limit(limit)
        ).scalars()
    )
