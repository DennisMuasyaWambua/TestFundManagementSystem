"""Opening balance migration endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import PlainTextResponse

from app.api.deps import CurrentUser, DbSession, guard_client, needs
from app.errors import BusinessRule
from app.models import FileKind, OpeningBalanceBatch, User
from app.schemas.models import (
    AcknowledgeWarningsRequest,
    BatchDetail,
    BatchPostedResponse,
    BatchRow,
    CreateBatchRequest,
    PreviewBody,
    ReasonRequest,
    ValidationReportBody,
)
from app.services import files as files_svc
from app.services import opening_balances as ob
from app.services.permissions import Permission

router = APIRouter(tags=["opening-balances"])
PREPARE = needs(Permission.OPENING_BALANCE_PREPARE)
APPROVE = needs(Permission.OPENING_BALANCE_APPROVE)

KIND_FIELDS = {
    "holdings": "holdings",
    "lines": "lines",
    "custodian_balances": "BALANCE",
    "custodian_positions": "POSITION",
}


def _batch_row(batch: OpeningBalanceBatch) -> BatchRow:
    return BatchRow.model_validate(batch)


def _preview(db: DbSession, batch: OpeningBalanceBatch) -> PreviewBody:
    preview = ob.preview(db, batch)
    return PreviewBody(
        batch_id=preview.batch_id,
        client_id=preview.client_id,
        cutover_date=preview.cutover_date,
        lines=[
            {
                "account_code": line.account_code,
                "account_name": line.account_name,
                "holding_id": line.holding_id,
                "currency": line.currency,
                "debit": line.debit,
                "credit": line.credit,
                "description": line.description,
                "derived": line.derived,
            }
            for line in preview.lines
        ],
        total_debit=preview.total_debit,
        total_credit=preview.total_credit,
        section_a=preview.section_a,
        section_b=preview.section_b,
        suspense=preview.suspense,
        balanced=preview.balanced,
        reconciles=preview.reconciles,
        holdings=preview.holdings,
        validation=(
            ValidationReportBody.model_validate(preview.validation) if preview.validation else None
        ),
    )


@router.get("/opening-balances/templates/{name}.csv", response_class=PlainTextResponse)
def template(name: str, _: CurrentUser) -> PlainTextResponse:
    return PlainTextResponse(
        ob.template(name),
        media_type="text/csv",
        headers={"content-disposition": f'attachment; filename="{name}.csv"'},
    )


@router.get("/opening-balances", response_model=list[BatchRow])
def list_batches(db: DbSession, _: CurrentUser, client: str | None = None) -> list[BatchRow]:
    return [_batch_row(batch) for batch in ob.list_batches(db, client_id=client)]


@router.post("/opening-balances", response_model=BatchRow, status_code=201)
def create_batch(body: CreateBatchRequest, db: DbSession, actor: User = PREPARE) -> BatchRow:
    guard_client(db, actor, body.client_id)
    batch = ob.create_batch(
        db,
        client_id=body.client_id,
        cutover_date=body.cutover_date,
        prepared_by=actor.id,
        profit_treatment=body.profit_treatment,
        pro_rata_accrual_split=body.pro_rata_accrual_split,
    )
    return _batch_row(batch)


@router.post("/opening-balances/{batch_id}/files", response_model=BatchRow)
def upload_file(
    batch_id: int,
    db: DbSession,
    kind: Annotated[str, Form()],
    upload: Annotated[UploadFile, File()],
    actor: User = PREPARE,
) -> BatchRow:
    """Stage one CSV.  The file is stored with its SHA-256 before the rows are read."""
    if kind not in KIND_FIELDS:
        raise BusinessRule(
            f"unknown file kind {kind!r}; expected one of {', '.join(KIND_FIELDS)}", kind=kind
        )
    batch = ob.get_batch(db, batch_id)
    guard_client(db, actor, batch.client_id)
    raw = upload.file.read()
    stored = files_svc.store(
        db,
        kind=FileKind.OPENING_BALANCE_CSV,
        filename=upload.filename or f"{kind}.csv",
        content=raw,
        uploaded_by=actor.id,
        content_type="text/csv",
    )
    text = raw.decode("utf-8-sig")
    if kind == "holdings":
        rows = ob.load_holdings(db, batch, text)
    elif kind == "lines":
        rows = ob.load_lines(db, batch, text)
    else:
        rows = ob.load_custodian_rows(db, batch, text, kind=KIND_FIELDS[kind])

    source_files = dict(batch.source_files or {})
    source_files[kind] = {
        "file_id": stored.id,
        "filename": stored.filename,
        "sha256": stored.sha256,
        "rows": rows,
    }
    batch.source_files = source_files
    db.flush()
    return _batch_row(batch)


@router.post("/opening-balances/{batch_id}/validate", response_model=ValidationReportBody)
def validate_batch(batch_id: int, db: DbSession, actor: User = PREPARE) -> ValidationReportBody:
    batch = ob.get_batch(db, batch_id)
    guard_client(db, actor, batch.client_id)
    report = ob.validate(db, batch)
    return ValidationReportBody.model_validate(report.as_dict())


@router.get("/opening-balances/{batch_id}", response_model=BatchDetail)
def get_batch(batch_id: int, db: DbSession, user: CurrentUser) -> BatchDetail:
    batch = ob.get_batch(db, batch_id)
    guard_client(db, user, batch.client_id)
    return BatchDetail(
        batch=_batch_row(batch),
        validation=(
            ValidationReportBody.model_validate(batch.validation_report)
            if batch.validation_report
            else None
        ),
        preview=_preview(db, batch),
    )


@router.post("/opening-balances/{batch_id}/acknowledge-warnings", response_model=BatchRow)
def acknowledge(
    batch_id: int,
    body: AcknowledgeWarningsRequest,
    db: DbSession,
    actor: User = PREPARE,
) -> BatchRow:
    batch = ob.get_batch(db, batch_id)
    guard_client(db, actor, batch.client_id)
    ob.acknowledge_warnings(db, batch, user_id=actor.id, note=body.note)
    return _batch_row(batch)


@router.post("/opening-balances/{batch_id}/submit", response_model=BatchRow)
def submit(batch_id: int, db: DbSession, actor: User = PREPARE) -> BatchRow:
    batch = ob.get_batch(db, batch_id)
    guard_client(db, actor, batch.client_id)
    ob.submit(db, batch, user_id=actor.id)
    return _batch_row(batch)


@router.post("/opening-balances/{batch_id}/approve", response_model=BatchPostedResponse)
def approve(batch_id: int, db: DbSession, actor: User = APPROVE) -> BatchPostedResponse:
    batch = ob.get_batch(db, batch_id)
    guard_client(db, actor, batch.client_id)
    result = ob.approve(db, batch, approver=actor)
    return BatchPostedResponse(
        batch=_batch_row(result.batch),
        journal_entry_id=result.entry.id,
        holdings_created=result.holdings_created,
        reconciliation_breaks=len(result.reconciliation.breaks),
        locked_through=result.locked_through,
    )


@router.post("/opening-balances/{batch_id}/reject", response_model=BatchRow)
def reject(batch_id: int, body: ReasonRequest, db: DbSession, actor: User = APPROVE) -> BatchRow:
    batch = ob.get_batch(db, batch_id)
    guard_client(db, actor, batch.client_id)
    ob.reject(db, batch, approver=actor, reason=body.reason)
    return _batch_row(batch)
