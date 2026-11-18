"""Valuations, period end, reconciliation, the journal and the audit log."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, guard_client, needs
from app.enums import LedgerEvent
from app.models import AuditLog, JournalEntry, User, Valuation
from app.schemas.common import AuditEntry, Page
from app.schemas.models import (
    AccrualLineRow,
    AccrualRunResponse,
    ChecklistItemRow,
    ChecklistResponse,
    CloseRequest,
    CloseResponse,
    CreateValuationRequest,
    CustodianBalanceRequest,
    CustodianPositionRequest,
    JournalEntryRow,
    ManualJournalRequest,
    ManualJournalRow,
    ReasonRequest,
    ReconLineRow,
    ReconResponse,
    ReconRunRow,
    RevaluationLineRow,
    RevaluationResponse,
    ValuationRow,
)
from app.services import accruals as accruals_svc
from app.services import auth as auth_svc
from app.services import closing as closing_svc
from app.services import fx as fx_svc
from app.services import manual_journals as manual_svc
from app.services import reconciliation as recon_svc
from app.services import reports as reports_svc
from app.services import valuation as valuation_svc
from app.services.permissions import Permission

router = APIRouter(tags=["operations"])
LEDGER_OPS = needs(Permission.LEDGER_OPERATIONS)
VALUE_PROPOSE = needs(Permission.VALUATION_PROPOSE)
VALUE_APPROVE = needs(Permission.VALUATION_APPROVE)
STATEMENTS = needs(Permission.CUSTODIAN_STATEMENT_RECORD)
RECON = needs(Permission.RECONCILIATION_RUN)
JOURNAL = needs(Permission.JOURNAL_VIEW)
AUDIT = needs(Permission.AUDIT_VIEW)


# --- Valuations --------------------------------------------------------------


@router.get("/valuations", response_model=list[ValuationRow])
def list_valuations(
    db: DbSession, user: CurrentUser, client: str | None = None, status: str | None = None
) -> list[ValuationRow]:
    stmt = select(Valuation).order_by(Valuation.id.desc())
    if client:
        guard_client(db, user, client)
        stmt = stmt.where(Valuation.client_id == client)
    else:
        allowed = auth_svc.accessible_clients(db, user)
        if allowed is not None:
            stmt = stmt.where(Valuation.client_id.in_(allowed))
    if status:
        stmt = stmt.where(Valuation.status == status)
    return [ValuationRow.model_validate(row) for row in db.execute(stmt).scalars()]


@router.post("/valuations", response_model=ValuationRow, status_code=201)
def propose_valuation(
    body: CreateValuationRequest, db: DbSession, actor: User = VALUE_PROPOSE
) -> ValuationRow:
    valuation = valuation_svc.propose(
        db,
        holding_id=body.holding_id,
        valuation_date=body.valuation_date,
        source=body.source,
        prepared_by=actor.id,
        price=body.price,
        value=body.value,
        valuer_name=body.valuer_name,
        report_ref=body.report_ref,
        report_file_id=body.report_file_id,
    )
    guard_client(db, actor, valuation.client_id)
    return ValuationRow.model_validate(valuation)


@router.post("/valuations/{valuation_id}/approve", response_model=ValuationRow)
def approve_valuation(
    valuation_id: int, db: DbSession, actor: User = VALUE_APPROVE
) -> ValuationRow:
    valuation = valuation_svc.approve(db, valuation_id, approver_id=actor.id)
    return ValuationRow.model_validate(valuation)


@router.post("/valuations/{valuation_id}/reject", response_model=ValuationRow)
def reject_valuation(
    valuation_id: int, body: ReasonRequest, db: DbSession, actor: User = VALUE_APPROVE
) -> ValuationRow:
    valuation = valuation_svc.reject(db, valuation_id, approver_id=actor.id, reason=body.reason)
    return ValuationRow.model_validate(valuation)


# --- Period end --------------------------------------------------------------


@router.post("/clients/{client_id}/accruals", response_model=AccrualRunResponse)
def run_accruals(
    client_id: str,
    db: DbSession,
    as_of: date,
    actor: User = LEDGER_OPS,
) -> AccrualRunResponse:
    guard_client(db, actor, client_id)
    run = accruals_svc.run(db, client_id, as_of, created_by=actor.id)
    return AccrualRunResponse(
        client_id=run.client_id,
        as_of=run.as_of,
        lines=[AccrualLineRow(**line.__dict__) for line in run.lines],
        rent_invoices=run.rent_invoices,
        skipped=run.skipped,
        profit_posted=run.profit_posted,
        fee_posted=run.fee_posted,
        changed=run.changed,
    )


@router.post("/clients/{client_id}/fx-revaluation", response_model=RevaluationResponse)
def run_revaluation(
    client_id: str, db: DbSession, as_of: date, actor: User = LEDGER_OPS
) -> RevaluationResponse:
    guard_client(db, actor, client_id)
    result = fx_svc.revalue(db, client_id, as_of, created_by=actor.id)
    return RevaluationResponse(
        client_id=result.client_id,
        as_of=result.as_of,
        lines=[
            RevaluationLineRow(
                account_code=line.account_code,
                holding_id=line.holding_id,
                currency=line.currency,
                own_amount=line.own_amount,
                base_before=line.base_before,
                base_after=line.base_after,
                delta=line.delta,
            )
            for line in result.lines
        ],
        net=result.net,
        changed=result.changed,
    )


@router.get("/clients/{client_id}/close-checklist", response_model=ChecklistResponse)
def close_checklist(
    client_id: str, db: DbSession, user: CurrentUser, period_end: date
) -> ChecklistResponse:
    guard_client(db, user, client_id)
    checklist = closing_svc.checklist(db, client_id, period_end)
    return ChecklistResponse(
        client_id=checklist.client_id,
        period_end=checklist.period_end,
        items=[ChecklistItemRow(**item.__dict__) for item in checklist.items],
        can_close=checklist.can_close,
    )


@router.post("/clients/{client_id}/close", response_model=CloseResponse)
def close_period(
    client_id: str,
    body: CloseRequest,
    db: DbSession,
    period_end: date,
    actor: User = LEDGER_OPS,
) -> CloseResponse:
    guard_client(db, actor, client_id)
    result = closing_svc.close(
        db, client_id, period_end, created_by=actor.id, override_reason=body.override_reason
    )
    return CloseResponse(
        client_id=result.client_id,
        period_end=result.period_end,
        net_profit=result.net_profit,
        journal_entry_id=result.entry.id if result.entry else None,
        locked_through=result.locked_through,
        already_closed=result.already_closed,
    )


# --- Reconciliation ----------------------------------------------------------


@router.post("/custodian-balances", status_code=201, response_model=ReconLineRow)
def record_custodian_balance(
    body: CustodianBalanceRequest, db: DbSession, actor: User = STATEMENTS
) -> ReconLineRow:
    row = recon_svc.record_balance(
        db,
        custody_account_id=body.custody_account_id,
        as_of=body.as_of,
        balance=body.balance,
        statement_ref=body.statement_ref,
        recorded_by=actor.id,
        source_file_id=body.source_file_id,
    )
    return ReconLineRow(
        scope="CASH",
        key=row.custody_account_id,
        label=row.statement_ref,
        currency="",
        ledger="",
        custodian=f"{row.balance:.2f}",
        difference="",
        matched=True,
        note=row.statement_ref,
    )


@router.post("/custodian-positions", status_code=201, response_model=ReconLineRow)
def record_custodian_position(
    body: CustodianPositionRequest, db: DbSession, actor: User = STATEMENTS
) -> ReconLineRow:
    row = recon_svc.record_position(
        db,
        holding_id=body.holding_id,
        as_of=body.as_of,
        amount=body.amount,
        statement_ref=body.statement_ref,
        recorded_by=actor.id,
        source_file_id=body.source_file_id,
    )
    return ReconLineRow(
        scope="POSITION",
        key=row.holding_id,
        label=row.statement_ref,
        currency="",
        ledger="",
        custodian=f"{row.amount:.2f}",
        difference="",
        matched=True,
        note=row.statement_ref,
    )


@router.post("/reconciliations", response_model=ReconResponse, status_code=201)
def run_reconciliation(
    db: DbSession,
    as_of: date,
    client: str | None = None,
    scope: str = "BOTH",
    actor: User = RECON,
) -> ReconResponse:
    if client:
        guard_client(db, actor, client)
    result = recon_svc.run(db, as_of=as_of, performed_by=actor.id, client_id=client, scope=scope)
    return ReconResponse(
        run_id=result.run_id,
        as_of=result.as_of,
        client_id=result.client_id,
        lines=[ReconLineRow(**line.__dict__) for line in result.lines],
        breaks=len(result.breaks),
    )


@router.get("/reconciliations", response_model=list[ReconRunRow])
def list_reconciliations(db: DbSession, _: CurrentUser) -> list[ReconRunRow]:
    return [ReconRunRow.model_validate(row) for row in recon_svc.latest_runs(db)]


@router.get("/reconciliations/{run_id}", response_model=ReconResponse)
def get_reconciliation(run_id: int, db: DbSession, _: CurrentUser) -> ReconResponse:
    from app.errors import NotFound
    from app.models import ReconciliationRun

    row = db.get(ReconciliationRun, run_id)
    if row is None:
        raise NotFound(f"unknown reconciliation run {run_id}", run_id=run_id)
    lines = [ReconLineRow(**line) for line in (row.result or {}).get("lines", [])]
    return ReconResponse(
        run_id=row.id,
        as_of=row.as_of,
        client_id=row.client_id,
        lines=lines,
        breaks=row.breaks,
    )


# --- Journal -----------------------------------------------------------------


@router.get("/journal", response_model=Page[JournalEntryRow])
def search_journal(
    db: DbSession,
    user: CurrentUser,
    client: str | None = None,
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    account: str | None = None,
    holding: str | None = None,
    event: LedgerEvent | None = None,
    limit: int = Query(default=50, le=500),
    offset: int = 0,
) -> Page[JournalEntryRow]:
    if client:
        guard_client(db, user, client)
    entries, total = reports_svc.journal_search(
        db,
        client_id=client,
        from_date=from_date,
        to_date=to_date,
        account_code=account,
        holding_id=holding,
        event=event,
        limit=limit,
        offset=offset,
    )
    return Page[JournalEntryRow](
        items=[JournalEntryRow.model_validate(entry) for entry in entries],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/journal/{entry_id}", response_model=JournalEntryRow)
def get_journal_entry(entry_id: int, db: DbSession, user: CurrentUser) -> JournalEntryRow:
    from app.errors import NotFound

    entry = db.get(JournalEntry, entry_id)
    if entry is None:
        raise NotFound(f"unknown journal entry {entry_id}", entry_id=entry_id)
    guard_client(db, user, entry.client_id)
    return JournalEntryRow.model_validate(entry)


@router.post("/journal/{entry_id}/reverse", response_model=JournalEntryRow)
def reverse_journal_entry(
    entry_id: int, body: ReasonRequest, db: DbSession, actor: User = LEDGER_OPS
) -> JournalEntryRow:
    from app.ledger.reversal import reverse_entry

    reversal = reverse_entry(db, entry_id, reason=body.reason, created_by=actor.id)
    return JournalEntryRow.model_validate(reversal)


@router.get("/journal/manual/pending", response_model=list[ManualJournalRow])
def pending_manual_journals(
    db: DbSession, _: User = JOURNAL, client: str | None = None
) -> list[ManualJournalRow]:
    return [
        ManualJournalRow.model_validate(
            {
                "id": row.id,
                "client_id": row.client_id,
                "entry_date": row.entry_date,
                "narrative": row.narrative,
                "status": str(row.status),
                "prepared_by": row.prepared_by,
                "approved_by": row.approved_by,
                "journal_entry_id": row.journal_entry_id,
                "lines": row.lines,
            }
        )
        for row in manual_svc.pending(db, client_id=client)
    ]


@router.post("/journal/manual", response_model=ManualJournalRow, status_code=201)
def propose_manual_journal(
    body: ManualJournalRequest, db: DbSession, actor: User = LEDGER_OPS
) -> ManualJournalRow:
    guard_client(db, actor, body.client_id)
    row = manual_svc.propose(
        db,
        client_id=body.client_id,
        entry_date=body.entry_date,
        narrative=body.narrative,
        lines=[line.model_dump() for line in body.lines],
        prepared_by=actor.id,
    )
    return ManualJournalRow.model_validate(
        {
            "id": row.id,
            "client_id": row.client_id,
            "entry_date": row.entry_date,
            "narrative": row.narrative,
            "status": str(row.status),
            "prepared_by": row.prepared_by,
            "approved_by": row.approved_by,
            "journal_entry_id": row.journal_entry_id,
            "lines": row.lines,
        }
    )


@router.post("/journal/manual/{journal_id}/approve", response_model=JournalEntryRow)
def approve_manual_journal(
    journal_id: int, db: DbSession, actor: User = LEDGER_OPS
) -> JournalEntryRow:
    _, entry = manual_svc.approve(db, journal_id, approver_id=actor.id)
    return JournalEntryRow.model_validate(entry)


@router.post("/journal/manual/{journal_id}/reject", response_model=ManualJournalRow)
def reject_manual_journal(
    journal_id: int, body: ReasonRequest, db: DbSession, actor: User = LEDGER_OPS
) -> ManualJournalRow:
    row = manual_svc.reject(db, journal_id, approver_id=actor.id, reason=body.reason)
    return ManualJournalRow.model_validate(
        {
            "id": row.id,
            "client_id": row.client_id,
            "entry_date": row.entry_date,
            "narrative": row.narrative,
            "status": str(row.status),
            "prepared_by": row.prepared_by,
            "approved_by": row.approved_by,
            "journal_entry_id": row.journal_entry_id,
            "lines": row.lines,
        }
    )


# --- Audit -------------------------------------------------------------------


@router.get("/audit-log", response_model=Page[AuditEntry])
def audit_log(
    db: DbSession,
    _: User = AUDIT,
    user: str | None = None,
    entity: str | None = None,
    client: str | None = None,
    action: str | None = None,
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    limit: int = Query(default=100, le=500),
    offset: int = 0,
) -> Page[AuditEntry]:
    from datetime import datetime, time

    from sqlalchemy import func

    stmt = select(AuditLog).order_by(AuditLog.id.desc())
    count_stmt = select(func.count()).select_from(AuditLog)
    filters = []
    if user:
        filters.append(AuditLog.user_id == user)
    if entity:
        filters.append(AuditLog.entity == entity)
    if client:
        filters.append(AuditLog.client_id == client)
    if action:
        filters.append(AuditLog.action == action)
    if from_date:
        filters.append(AuditLog.at >= datetime.combine(from_date, time.min))
    if to_date:
        filters.append(AuditLog.at <= datetime.combine(to_date, time.max))
    for condition in filters:
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)
    total = int(db.execute(count_stmt).scalar_one())
    rows = db.execute(stmt.limit(limit).offset(offset)).scalars()
    return Page[AuditEntry](
        items=[AuditEntry.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
