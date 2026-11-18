"""Holdings and money-in endpoints."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession, guard_client, needs
from app.enums import AssetClass, HoldingStatus
from app.models import Holding, User
from app.schemas.models import (
    ContributionRequest,
    HoldingBalances,
    HoldingDetail,
    HoldingListRow,
    HoldingRow,
    JournalEntryRow,
    MaturityRequest,
    PrincipalReceiptRequest,
    ProfitReceiptRequest,
    ReceiptResponse,
    RentReceiptRequest,
    TenantDepositRequest,
    ValuationRow,
    WriteOffRequest,
)
from app.services import holdings as holdings_svc
from app.services import receipts as receipts_svc
from app.services import reports as reports_svc
from app.services import valuation as valuation_svc
from app.services.permissions import Permission

router = APIRouter(tags=["holdings"])
RECEIPTS = needs(Permission.RECEIPT_RECORD)
LEDGER_OPS = needs(Permission.LEDGER_OPERATIONS)


@router.get("/holdings", response_model=list[HoldingListRow])
def list_holdings(
    db: DbSession,
    user: CurrentUser,
    client: str | None = None,
    asset_class: AssetClass | None = None,
    status: HoldingStatus | None = None,
    as_of: str | None = None,
) -> list[HoldingListRow]:
    from sqlalchemy import select

    from app.services import auth as auth_svc

    stmt = select(Holding).order_by(Holding.client_id, Holding.id)
    if client:
        guard_client(db, user, client)
        stmt = stmt.where(Holding.client_id == client)
    else:
        allowed = auth_svc.accessible_clients(db, user)
        if allowed is not None:
            stmt = stmt.where(Holding.client_id.in_(allowed))
    if asset_class:
        stmt = stmt.where(Holding.asset_class == asset_class)
    if status:
        stmt = stmt.where(Holding.status == status)

    when = date.fromisoformat(as_of) if as_of else date.today()
    return [
        HoldingListRow(
            holding=HoldingRow.model_validate(row),
            balances=_balances(db, row, when),
        )
        for row in db.execute(stmt).scalars()
    ]


def _balances(db: DbSession, holding: Holding, when: date) -> HoldingBalances:
    """The ledger balances for one holding, in the shape both endpoints return."""
    summary = holdings_svc.summarise(db, holding, when)
    return HoldingBalances(
        outstanding=summary.outstanding,
        accrued_profit=summary.accrued_profit,
        rent_receivable=summary.rent_receivable,
        fair_value_adjustment=summary.fair_value_adjustment,
        fair_value=summary.fair_value,
        income_recognised=summary.income_recognised,
        fee_charged=summary.fee_charged,
        profit_to_date=summary.profit_to_date,
    )


@router.get("/holdings/{holding_id}", response_model=HoldingDetail)
def get_holding(
    holding_id: str, db: DbSession, user: CurrentUser, as_of: str | None = None
) -> HoldingDetail:
    holding = holdings_svc.get_holding(db, holding_id)
    guard_client(db, user, holding.client_id)
    when = date.fromisoformat(as_of) if as_of else date.today()
    entries, _ = reports_svc.journal_search(
        db, client_id=holding.client_id, holding_id=holding_id, limit=200
    )
    return HoldingDetail(
        holding=HoldingRow.model_validate(holding),
        balances=_balances(db, holding, when),
        valuations=[
            ValuationRow.model_validate(row) for row in valuation_svc.history(db, holding_id)
        ],
        journal=[JournalEntryRow.model_validate(entry) for entry in entries],
    )


@router.post("/contributions", response_model=ReceiptResponse, status_code=201)
def record_contribution(
    body: ContributionRequest, db: DbSession, actor: User = RECEIPTS
) -> ReceiptResponse:
    guard_client(db, actor, body.client_id)
    receipt = receipts_svc.record_contribution(
        db,
        client_id=body.client_id,
        custody_account_id=body.custody_account_id,
        amount=body.amount,
        value_date=body.value_date,
        advice_ref=body.advice_ref,
        created_by=actor.id,
        narrative=body.narrative,
    )
    return ReceiptResponse(
        journal_entry_id=receipt.entry.id, holding_id=None, true_up=receipt.true_up
    )


def _receipt(receipt: receipts_svc.Receipt) -> ReceiptResponse:
    return ReceiptResponse(
        journal_entry_id=receipt.entry.id,
        holding_id=receipt.holding_id,
        true_up=receipt.true_up,
    )


@router.post("/holdings/{holding_id}/profit", response_model=ReceiptResponse, status_code=201)
def record_profit(
    holding_id: str,
    body: ProfitReceiptRequest,
    db: DbSession,
    actor: User = RECEIPTS,
) -> ReceiptResponse:
    holding = holdings_svc.get_holding(db, holding_id)
    guard_client(db, actor, holding.client_id)
    return _receipt(
        receipts_svc.record_profit(
            db,
            holding_id=holding_id,
            gross=body.gross,
            wht=body.wht,
            value_date=body.value_date,
            advice_ref=body.advice_ref,
            created_by=actor.id,
        )
    )


@router.post("/holdings/{holding_id}/principal", response_model=ReceiptResponse, status_code=201)
def record_principal(
    holding_id: str,
    body: PrincipalReceiptRequest,
    db: DbSession,
    actor: User = RECEIPTS,
) -> ReceiptResponse:
    holding = holdings_svc.get_holding(db, holding_id)
    guard_client(db, actor, holding.client_id)
    return _receipt(
        receipts_svc.record_principal(
            db,
            holding_id=holding_id,
            amount=body.amount,
            value_date=body.value_date,
            advice_ref=body.advice_ref,
            created_by=actor.id,
        )
    )


@router.post("/holdings/{holding_id}/maturity", response_model=ReceiptResponse, status_code=201)
def record_maturity(
    holding_id: str,
    body: MaturityRequest,
    db: DbSession,
    actor: User = RECEIPTS,
) -> ReceiptResponse:
    holding = holdings_svc.get_holding(db, holding_id)
    guard_client(db, actor, holding.client_id)
    return _receipt(
        receipts_svc.record_maturity(
            db,
            holding_id=holding_id,
            principal=body.principal,
            profit=body.profit,
            wht=body.wht,
            value_date=body.value_date,
            advice_ref=body.advice_ref,
            created_by=actor.id,
        )
    )


@router.post("/holdings/{holding_id}/rent", response_model=ReceiptResponse, status_code=201)
def record_rent(
    holding_id: str, body: RentReceiptRequest, db: DbSession, actor: User = RECEIPTS
) -> ReceiptResponse:
    holding = holdings_svc.get_holding(db, holding_id)
    guard_client(db, actor, holding.client_id)
    return _receipt(
        receipts_svc.record_rent(
            db,
            holding_id=holding_id,
            gross=body.gross,
            wht=body.wht,
            value_date=body.value_date,
            advice_ref=body.advice_ref,
            created_by=actor.id,
        )
    )


@router.post(
    "/holdings/{holding_id}/tenant-deposit", response_model=ReceiptResponse, status_code=201
)
def record_tenant_deposit(
    holding_id: str, body: TenantDepositRequest, db: DbSession, actor: User = RECEIPTS
) -> ReceiptResponse:
    holding = holdings_svc.get_holding(db, holding_id)
    guard_client(db, actor, holding.client_id)
    return _receipt(
        receipts_svc.record_tenant_deposit(
            db,
            holding_id=holding_id,
            amount=body.amount,
            value_date=body.value_date,
            advice_ref=body.advice_ref,
            created_by=actor.id,
        )
    )


@router.post("/holdings/{holding_id}/write-off", response_model=ReceiptResponse, status_code=201)
def write_off(
    holding_id: str, body: WriteOffRequest, db: DbSession, actor: User = LEDGER_OPS
) -> ReceiptResponse:
    holding = holdings_svc.get_holding(db, holding_id)
    guard_client(db, actor, holding.client_id)
    return _receipt(
        receipts_svc.write_off(
            db, holding_id=holding_id, on=body.on, reason=body.reason, created_by=actor.id
        )
    )
