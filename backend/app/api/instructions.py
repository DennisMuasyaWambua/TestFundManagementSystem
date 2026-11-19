"""Custody instruction endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Query, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, DbSession, guard_client, needs
from app.enums import InstructionStatus, InstructionType, UserRole
from app.models import CustodyAccount, FileKind, Holding, Instruction, JournalEntry, User
from app.schemas.models import (
    ApprovalRow,
    CashPositionRow,
    CheckRow,
    CreateInstructionRequest,
    HoldingRow,
    InstructionDetail,
    InstructionRow,
    JournalEntryRow,
    ReasonRequest,
    SettleInstructionRequest,
)
from app.services import auth as auth_svc
from app.services import files as files_svc
from app.services import instructions as ins_svc
from app.services.permissions import Permission

router = APIRouter(tags=["instructions"])
CREATE = needs(Permission.INSTRUCTION_CREATE)
APPROVE = needs(Permission.INSTRUCTION_APPROVE)
DISPATCH = needs(Permission.INSTRUCTION_DISPATCH)


def _row(db: Session, instruction: Instruction) -> InstructionRow:
    approvals = []
    for approval in instruction.approvals:
        user = db.get(User, approval.user_id)
        approvals.append(
            ApprovalRow(
                user_id=approval.user_id,
                user_name=user.name if user else approval.user_id,
                title=user.title if user else "",
                approved_at=approval.approved_at,
            )
        )
    row = InstructionRow.model_validate(instruction)
    return row.model_copy(update={"approvals": approvals})


@router.get("/instructions", response_model=list[InstructionRow])
def list_instructions(
    db: DbSession,
    user: CurrentUser,
    client: str | None = None,
    status: InstructionStatus | None = None,
    mine: bool = False,
    limit: int = Query(default=100, le=500),
) -> list[InstructionRow]:
    if mine:
        return [_row(db, item) for item in ins_svc.awaiting(db, user)]
    stmt = select(Instruction).order_by(Instruction.id.desc()).limit(limit)
    if client:
        guard_client(db, user, client)
        stmt = stmt.where(Instruction.client_id == client)
    else:
        allowed = auth_svc.accessible_clients(db, user)
        if allowed is not None:
            stmt = stmt.where(Instruction.client_id.in_(allowed))
    if status:
        stmt = stmt.where(Instruction.status == status)
    return [_row(db, item) for item in db.execute(stmt).scalars()]


@router.get("/instructions/cash-position", response_model=CashPositionRow)
def cash_position(custody_account_id: str, db: DbSession, user: CurrentUser) -> CashPositionRow:
    account = db.get(CustodyAccount, custody_account_id)
    if account is None:
        from app.errors import NotFound

        raise NotFound(
            f"unknown custody account {custody_account_id}",
            custody_account_id=custody_account_id,
        )
    guard_client(db, user, account.client_id)
    position = ins_svc.cash_position(db, account)
    return CashPositionRow(
        custody_account_id=position.custody_account_id,
        currency=position.currency,
        ledger=position.ledger,
        committed=position.committed,
        available=position.available,
    )


@router.post("/instructions", response_model=InstructionRow, status_code=201)
def create_instruction(
    body: CreateInstructionRequest, db: DbSession, actor: User = CREATE
) -> InstructionRow:
    guard_client(db, actor, body.client_id)
    instruction = ins_svc.create(
        db,
        client_id=body.client_id,
        custody_account_id=body.custody_account_id,
        instruction_type=InstructionType(body.type),
        amount=body.amount,
        value_date=body.value_date,
        maker_id=actor.id,
        beneficiary=body.beneficiary,
        beneficiary_account=body.beneficiary_account,
        narrative=body.narrative,
        client_instruction_ref=body.client_instruction_ref,
        params=body.params,
    )
    return _row(db, instruction)


@router.post("/instructions/checks", response_model=list[CheckRow])
def preflight_checks(
    body: CreateInstructionRequest, db: DbSession, actor: User = CREATE
) -> list[CheckRow]:
    """Run the gate checks without creating anything -- the live panel on the form."""
    from app.services import clients as clients_svc

    guard_client(db, actor, body.client_id)
    client = clients_svc.get(db, body.client_id)
    account = db.get(CustodyAccount, body.custody_account_id)
    if account is None or account.client_id != body.client_id:
        from app.errors import NotFound

        raise NotFound(
            f"unknown custody account {body.custody_account_id}",
            custody_account_id=body.custody_account_id,
        )
    checks = ins_svc.gate_checks(
        db,
        client=client,
        custody=account,
        instruction_type=InstructionType(body.type),
        amount=body.amount,
        client_instruction_ref=body.client_instruction_ref,
        params=body.params,
    )
    return [CheckRow(**check.__dict__) for check in checks]


@router.get("/instructions/{instruction_id}", response_model=InstructionDetail)
def get_instruction(instruction_id: int, db: DbSession, user: CurrentUser) -> InstructionDetail:
    instruction = db.get(Instruction, instruction_id)
    if instruction is None:
        from app.errors import NotFound

        raise NotFound(f"unknown instruction {instruction_id}", instruction_id=instruction_id)
    guard_client(db, user, instruction.client_id)
    holding = db.get(Holding, instruction.holding_id) if instruction.holding_id else None
    entry = (
        db.get(JournalEntry, instruction.journal_entry_id) if instruction.journal_entry_id else None
    )
    can_approve = (
        user.role is UserRole.SIGNATORY
        and instruction.status is InstructionStatus.PENDING_APPROVAL
        and all(approval.user_id != user.id for approval in instruction.approvals)
    )
    return InstructionDetail(
        instruction=_row(db, instruction),
        checks=[],
        holding=HoldingRow.model_validate(holding) if holding else None,
        journal=JournalEntryRow.model_validate(entry) if entry else None,
        can_approve=can_approve,
        can_dispatch=(
            instruction.status is InstructionStatus.APPROVED
            and user.role in (UserRole.MAKER, UserRole.FINANCE)
        ),
        can_settle=(
            instruction.status is InstructionStatus.SENT
            and user.role in (UserRole.MAKER, UserRole.FINANCE)
        ),
    )


@router.get("/instructions/{instruction_id}/letter.pdf")
def letter(instruction_id: int, db: DbSession, user: CurrentUser) -> Response:
    instruction = db.get(Instruction, instruction_id)
    if instruction is None:
        from app.errors import NotFound

        raise NotFound(f"unknown instruction {instruction_id}", instruction_id=instruction_id)
    guard_client(db, user, instruction.client_id)
    built = ins_svc.letter_for(db, instruction_id)
    return Response(
        content=built.pdf,
        media_type="application/pdf",
        headers={
            "content-disposition": f'inline; filename="{built.filename}"',
            "x-letter-sha256": built.sha256,
        },
    )


@router.post("/instructions/{instruction_id}/approve", response_model=InstructionRow)
def approve(instruction_id: int, db: DbSession, actor: User = APPROVE) -> InstructionRow:
    instruction = ins_svc.approve(db, instruction_id, approver=actor)
    guard_client(db, actor, instruction.client_id)
    return _row(db, instruction)


@router.post("/instructions/{instruction_id}/reject", response_model=InstructionRow)
def reject(
    instruction_id: int, body: ReasonRequest, db: DbSession, actor: User = APPROVE
) -> InstructionRow:
    instruction = ins_svc.reject(db, instruction_id, user=actor, reason=body.reason)
    return _row(db, instruction)


@router.post("/instructions/{instruction_id}/cancel", response_model=InstructionRow)
def cancel(
    instruction_id: int, body: ReasonRequest, db: DbSession, actor: User = CREATE
) -> InstructionRow:
    instruction = ins_svc.cancel(db, instruction_id, user=actor, reason=body.reason)
    return _row(db, instruction)


@router.post("/instructions/{instruction_id}/sent", response_model=InstructionRow)
def mark_sent(
    instruction_id: int,
    db: DbSession,
    signed_copy: Annotated[UploadFile, File()],
    actor: User = DISPATCH,
) -> InstructionRow:
    """Upload the wet-signed scan and mark the instruction as sent."""
    instruction = db.get(Instruction, instruction_id)
    if instruction is None:
        from app.errors import NotFound

        raise NotFound(f"unknown instruction {instruction_id}", instruction_id=instruction_id)
    guard_client(db, actor, instruction.client_id)
    raw = signed_copy.file.read()
    stored = files_svc.store(
        db,
        kind=FileKind.SIGNED_LETTER,
        filename=signed_copy.filename or f"{instruction.reference}-signed.pdf",
        content=raw,
        uploaded_by=actor.id,
        content_type=signed_copy.content_type or "application/pdf",
    )
    updated = ins_svc.mark_sent(
        db,
        instruction_id,
        user_id=actor.id,
        signed_copy_sha256=stored.sha256,
        signed_copy_blob_id=stored.id,
    )
    return _row(db, updated)


@router.post("/instructions/{instruction_id}/settle", response_model=InstructionRow)
def settle(
    instruction_id: int,
    body: SettleInstructionRequest,
    db: DbSession,
    actor: User = DISPATCH,
) -> InstructionRow:
    instruction = ins_svc.settle(
        db,
        instruction_id,
        user_id=actor.id,
        confirmation_ref=body.confirmation_ref,
        settled_on=body.settled_on,
        amount=body.amount,
    )
    guard_client(db, actor, instruction.client_id)
    return _row(db, instruction)
