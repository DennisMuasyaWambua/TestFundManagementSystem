"""The custody instruction lifecycle -- the only way money leaves a client account.

PENDING_APPROVAL -> (two signatory approvals) -> APPROVED
APPROVED -> (wet-signed letter scanned and uploaded) -> SENT
SENT -> (custodian confirmation, for exactly the instructed amount) -> SETTLED

Only the move to SETTLED touches the ledger.  Until the custodian confirms, nothing is
booked: the money has not moved.

This test system does not stop the person who prepared an instruction from also
being one of its two signatories -- see approve() below. The same signatory still
cannot sign twice, since that is enforced by a database constraint as well.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import (
    BusinessRule,
    Conflict,
    InsufficientCash,
    MakerCheckerBreach,
    NotFound,
    OnboardingIncomplete,
    PermissionDenied,
)
from app.ledger import balances
from app.ledger.posting import PostingContext, build_lines, post
from app.ledger.roles import Role, resolve
from app.ledger.rules import event_for
from app.models import (
    INVESTMENT_INSTRUCTIONS,
    PIPELINE_STATUSES,
    AssetClass,
    Client,
    CustodyAccount,
    Holding,
    HoldingStatus,
    Instruction,
    InstructionApproval,
    InstructionStatus,
    InstructionType,
    JournalEntry,
    RecordStatus,
    ReferenceSequence,
    User,
    UserRole,
    utcnow,
)
from app.money import ZERO, money, round_money
from app.services import audit
from app.services import fx as fx_svc
from app.services import holdings as holdings_svc
from app.services import letters as letters_svc

PAYOUT_TYPES = (InstructionType.PAY_CLIENT_PROFIT, InstructionType.RETURN_CAPITAL)
SETTLEMENT_RULES: dict[InstructionType, str] = {
    InstructionType.PLACE_WAKALA: "INVESTMENT_PLACED",
    InstructionType.BUY_SUKUK: "INVESTMENT_PLACED",
    InstructionType.DISBURSE_FINANCING: "INVESTMENT_PLACED",
    InstructionType.PURCHASE_PROPERTY: "INVESTMENT_PLACED",
    InstructionType.PAY_CLIENT_PROFIT: "PROFIT_PAID_TO_CLIENT",
    InstructionType.RETURN_CAPITAL: "CAPITAL_WITHDRAWAL",
    InstructionType.PAY_MGMT_FEE: "MGMT_FEE_PAID",
    InstructionType.PAY_CUSTODY_FEE: "CUSTODY_FEE_PAID",
}


@dataclass(frozen=True)
class CashPosition:
    custody_account_id: str
    currency: str
    ledger: Decimal
    committed: Decimal

    @property
    def available(self) -> Decimal:
        return money(self.ledger - self.committed)


# --- References --------------------------------------------------------------


def next_reference(
    db: Session, year: int, *, name: str = "INSTRUCTION", prefix: str = "INS"
) -> str:
    """``INS/<year>/<4-digit sequence>``, gap-free, taken under a row lock."""
    stmt = select(ReferenceSequence).where(
        ReferenceSequence.name == name, ReferenceSequence.year == year
    )
    if db.bind is not None and db.bind.dialect.name != "sqlite":
        stmt = stmt.with_for_update()
    row = db.execute(stmt).scalar_one_or_none()
    if row is None:
        row = ReferenceSequence(name=name, year=year, last_value=0)
        db.add(row)
        db.flush()
    row.last_value += 1
    db.flush()
    return f"{prefix}/{year}/{row.last_value:04d}"


# --- Cash available ----------------------------------------------------------


def cash_position(db: Session, custody_account: CustodyAccount) -> CashPosition:
    """Ledger cash minus everything already in the instruction pipeline.

    One client's money is never used for another, and money already committed to a
    pending, approved or sent instruction is not available twice.
    """
    ledger = balances.balance(
        db,
        client_id=custody_account.client_id,
        account_code=custody_account.cash_ledger_code,
        currency=custody_account.currency,
    )
    committed = db.execute(
        select(func.sum(Instruction.amount)).where(
            Instruction.custody_account_id == custody_account.id,
            Instruction.status.in_([str(s) for s in PIPELINE_STATUSES]),
        )
    ).scalar_one_or_none()
    return CashPosition(
        custody_account_id=custody_account.id,
        currency=custody_account.currency,
        ledger=ledger,
        committed=money(committed or 0),
    )


# --- Creation ----------------------------------------------------------------


@dataclass
class Check:
    key: str
    label: str
    passed: bool
    detail: str = ""


def _load(db: Session, client_id: str, custody_account_id: str) -> tuple[Client, CustodyAccount]:
    client = db.get(Client, client_id)
    if client is None:
        raise NotFound(f"unknown client {client_id}", client_id=client_id)
    custody = db.get(CustodyAccount, custody_account_id)
    if custody is None or custody.client_id != client_id:
        raise NotFound(
            f"unknown custody account {custody_account_id}",
            custody_account_id=custody_account_id,
        )
    if custody.status is not RecordStatus.ACTIVE:
        raise BusinessRule(
            f"custody account {custody_account_id} is {custody.status}",
            custody_account_id=custody_account_id,
        )
    return client, custody


def gate_checks(
    db: Session,
    *,
    client: Client,
    custody: CustodyAccount,
    instruction_type: InstructionType,
    amount: Decimal,
    client_instruction_ref: str | None,
    params: dict[str, Any],
) -> list[Check]:
    """Every check the maker's screen shows live, as data, in one place."""
    checks: list[Check] = []
    gaps = client.onboarding_gaps
    checks.append(
        Check(
            key="onboarding",
            label="Client agreement and KYC in place",
            passed=not gaps,
            detail="; ".join(gaps) or "KYC approved, agreement on file",
        )
    )
    checks.append(
        Check(
            key="custody_appointment",
            label="Custodian appointed in writing",
            passed=bool(custody.custody_agreement_ref),
            detail=custody.custody_agreement_ref or "no custody agreement reference on file",
        )
    )
    checks.append(
        Check(
            key="amount",
            label="Amount is more than zero",
            passed=amount > 0,
            detail=f"{amount:.2f}",
        )
    )

    net_out = _cash_leaving(db, client, instruction_type, amount, params)
    position = cash_position(db, custody)
    checks.append(
        Check(
            key="cash_available",
            label="Cash available in this custody account",
            passed=position.available >= net_out,
            detail=(
                f"{position.available:.2f} {position.currency} available "
                f"(ledger {position.ledger:.2f} less {position.committed:.2f} committed); "
                f"{net_out:.2f} needed"
            ),
        )
    )

    if instruction_type in INVESTMENT_INSTRUCTIONS:
        holding_id = str(params.get("holding_id", "") or "")
        shariah = str(params.get("shariah_cert_ref", "") or "")
        counterparty = str(params.get("counterparty", "") or "")
        checks.append(
            Check(
                key="deal_reference",
                label="Deal reference supplied",
                passed=bool(holding_id),
                detail=holding_id or "no deal reference",
            )
        )
        checks.append(
            Check(
                key="shariah_approval",
                label="Shariah approval reference supplied",
                passed=bool(shariah),
                detail=shariah or "no Shariah approval reference",
            )
        )
        checks.append(
            Check(
                key="deal_terms",
                label="Deal terms complete",
                passed=bool(counterparty) and not _missing_terms(instruction_type, params),
                detail=", ".join(_missing_terms(instruction_type, params)) or f"{counterparty}",
            )
        )
        checks.append(
            Check(
                key="related_party_limit",
                label="Related-party exposure within the 10% limit",
                passed=_related_party_ok(db, client, params, amount),
                detail=_related_party_detail(db, client, params, amount),
            )
        )

    if instruction_type in PAYOUT_TYPES:
        checks.append(
            Check(
                key="client_request",
                label="Client's written request on file",
                passed=bool(client_instruction_ref),
                detail=client_instruction_ref or "no client instruction reference",
            )
        )

    if instruction_type is InstructionType.PAY_CLIENT_PROFIT:
        owed = -balances.balance(
            db,
            client_id=client.id,
            account_code=resolve(db, client.id, Role.CLIENT_PROFIT),
            base=True,
        )
        checks.append(
            Check(
                key="profit_available",
                label="Profit owed to the client covers this payment",
                passed=owed >= amount,
                detail=f"{owed:.2f} {client.base_currency} owed",
            )
        )
    if instruction_type is InstructionType.RETURN_CAPITAL:
        capital = -balances.balance(
            db,
            client_id=client.id,
            account_code=resolve(db, client.id, Role.CLIENT_CAPITAL),
            base=True,
        )
        checks.append(
            Check(
                key="capital_available",
                label="Client capital covers this return",
                passed=capital >= amount,
                detail=f"{capital:.2f} {client.base_currency} capital",
            )
        )
    if instruction_type is InstructionType.PAY_MGMT_FEE:
        accrued = -balances.balance(
            db,
            client_id=client.id,
            account_code=resolve(db, client.id, Role.MGMT_FEE_PAYABLE),
            currency=custody.currency,
        )
        checks.append(
            Check(
                key="fee_accrued",
                label="Management fee accrued covers this payment",
                passed=accrued >= amount,
                detail=f"{accrued:.2f} {custody.currency} accrued",
            )
        )
    if instruction_type is InstructionType.PAY_CUSTODY_FEE:
        accrued = -balances.balance(
            db,
            client_id=client.id,
            account_code=resolve(db, client.id, Role.CUSTODY_FEE_PAYABLE),
            currency=custody.currency,
        )
        checks.append(
            Check(
                key="custody_fee_accrued",
                label="Custody fee accrued covers this payment",
                passed=accrued >= amount,
                detail=f"{accrued:.2f} {custody.currency} accrued",
            )
        )
    if instruction_type is InstructionType.FX_CONVERSION:
        target_id = str(params.get("target_custody_account_id", "") or "")
        target = db.get(CustodyAccount, target_id) if target_id else None
        buy = params.get("buy_amount")
        agreed = params.get("agreed_rate")
        checks.append(
            Check(
                key="fx_target",
                label="Target custody account belongs to this client",
                passed=target is not None
                and target.client_id == client.id
                and target.currency != custody.currency,
                detail=target_id or "no target account",
            )
        )
        checks.append(
            Check(
                key="fx_terms",
                label="Amount to receive and agreed rate supplied",
                passed=bool(buy) and bool(agreed) and Decimal(str(buy)) > 0,
                detail=f"buy {buy}, rate {agreed}",
            )
        )

    return checks


def _missing_terms(instruction_type: InstructionType, params: dict[str, Any]) -> list[str]:
    required: dict[InstructionType, tuple[str, ...]] = {
        InstructionType.PLACE_WAKALA: ("profit_rate", "maturity_date"),
        InstructionType.BUY_SUKUK: ("profit_rate", "maturity_date", "nominal"),
        InstructionType.DISBURSE_FINANCING: ("profit_rate", "maturity_date"),
        InstructionType.PURCHASE_PROPERTY: (),
    }
    return [key for key in required.get(instruction_type, ()) if not params.get(key)]


def _funds_under_management(db: Session, client: Client) -> Decimal:
    from app.models import AccountType

    rows = balances.by_account(db, client_id=client.id, types=(AccountType.ASSET,))
    return money(sum((row.base_amount for row in rows), Decimal(0)))


def _related_party_ok(db: Session, client: Client, params: dict[str, Any], amount: Decimal) -> bool:
    if not params.get("related_party"):
        return True
    limit = get_settings().related_party_limit_pct
    total = _funds_under_management(db, client)
    if total == 0:
        return False
    existing = money(
        sum(
            (
                holdings_svc.outstanding(db, holding)
                for holding in db.execute(
                    select(Holding).where(
                        Holding.client_id == client.id,
                        Holding.related_party.is_(True),
                        Holding.status == HoldingStatus.ACTIVE,
                    )
                ).scalars()
            ),
            Decimal(0),
        )
    )
    return (existing + amount) <= round_money(total * limit)


def _related_party_detail(
    db: Session, client: Client, params: dict[str, Any], amount: Decimal
) -> str:
    if not params.get("related_party"):
        return "not a related-party counterparty"
    total = _funds_under_management(db, client)
    limit = round_money(total * get_settings().related_party_limit_pct)
    return f"limit {limit:.2f} of {total:.2f} funds managed"


def _cash_leaving(
    db: Session,
    client: Client,
    instruction_type: InstructionType,
    amount: Decimal,
    params: dict[str, Any],
) -> Decimal:
    """How much actually leaves the custody account."""
    if instruction_type is InstructionType.PAY_CLIENT_PROFIT:
        wht = round_money(amount * client.final_wht_rate)
        return money(amount - wht)
    return money(amount)


def create(
    db: Session,
    *,
    client_id: str,
    custody_account_id: str,
    instruction_type: InstructionType,
    amount: Decimal,
    value_date: date,
    maker_id: str,
    beneficiary: str = "",
    beneficiary_account: str = "",
    narrative: str = "",
    client_instruction_ref: str | None = None,
    params: dict[str, Any] | None = None,
) -> Instruction:
    """Raise an instruction.  Every gate must pass before it reaches the signatories."""
    client, custody = _load(db, client_id, custody_account_id)
    params = dict(params or {})
    value = money(amount)

    checks = gate_checks(
        db,
        client=client,
        custody=custody,
        instruction_type=instruction_type,
        amount=value,
        client_instruction_ref=client_instruction_ref,
        params=params,
    )
    failures = [check for check in checks if not check.passed]
    if failures:
        first = failures[0]
        error_type = {
            "onboarding": OnboardingIncomplete,
            "custody_appointment": OnboardingIncomplete,
            "cash_available": InsufficientCash,
        }.get(first.key, BusinessRule)
        raise error_type(
            f"{first.label}: {first.detail}",
            failed_checks=[{"key": c.key, "label": c.label, "detail": c.detail} for c in failures],
        )

    if instruction_type is InstructionType.PAY_CLIENT_PROFIT:
        wht = round_money(value * client.final_wht_rate)
        params.setdefault("wht", f"{wht:.2f}")
        params.setdefault("net", f"{money(value - wht):.2f}")

    instruction = Instruction(
        reference=next_reference(db, value_date.year),
        client_id=client_id,
        custody_account_id=custody_account_id,
        type=instruction_type,
        amount=value,
        currency=custody.currency,
        value_date=value_date,
        beneficiary=beneficiary,
        beneficiary_account=beneficiary_account,
        narrative=narrative,
        client_instruction_ref=client_instruction_ref,
        params=params,
        status=InstructionStatus.PENDING_APPROVAL,
        maker_id=maker_id,
        created_by=maker_id,
    )
    db.add(instruction)
    db.flush()

    if instruction_type in INVESTMENT_INSTRUCTIONS:
        instruction.holding_id = _create_pending_holding(
            db, instruction, client=client, custody=custody, params=params, maker_id=maker_id
        )
        db.flush()

    audit.record(
        db,
        user_id=maker_id,
        action="INSTRUCTION_CREATED",
        entity="instruction",
        entity_id=instruction.id,
        client_id=client_id,
        detail={
            "reference": instruction.reference,
            "type": str(instruction_type),
            "amount": f"{value:.2f}",
            "currency": custody.currency,
            "value_date": value_date.isoformat(),
            "holding_id": instruction.holding_id,
            "checks": [{"key": c.key, "detail": c.detail} for c in checks],
        },
    )
    return instruction


def _create_pending_holding(
    db: Session,
    instruction: Instruction,
    *,
    client: Client,
    custody: CustodyAccount,
    params: dict[str, Any],
    maker_id: str,
) -> str:
    asset_class = INVESTMENT_INSTRUCTIONS[instruction.type]
    holding_id = str(params["holding_id"])
    if db.get(Holding, holding_id) is not None:
        raise Conflict(f"holding {holding_id} already exists", holding_id=holding_id)

    def opt_decimal(key: str) -> Decimal | None:
        raw = params.get(key)
        return Decimal(str(raw)) if raw not in (None, "") else None

    def opt_date(key: str) -> date | None:
        raw = params.get(key)
        return date.fromisoformat(str(raw)) if raw else None

    holding = Holding(
        id=holding_id,
        client_id=client.id,
        asset_class=asset_class,
        custody_account_id=custody.id,
        currency=custody.currency,
        counterparty=str(params.get("counterparty", "")),
        related_party=bool(params.get("related_party", False)),
        description=str(params.get("description", "")),
        face_amount=instruction.amount,
        nominal=opt_decimal("nominal"),
        profit_rate=opt_decimal("profit_rate"),
        day_basis=int(params.get("day_basis") or get_settings().default_day_basis),
        maturity_date=opt_date("maturity_date"),
        monthly_rent=opt_decimal("monthly_rent"),
        shariah_cert_ref=str(params.get("shariah_cert_ref", "")) or None,
        external_ref=str(params.get("external_ref", "")) or None,
        instruction_id=instruction.id,
        status=HoldingStatus.PENDING,
        created_by=maker_id,
    )
    db.add(holding)
    db.flush()
    return holding.id


# --- Approval ----------------------------------------------------------------


def approve(db: Session, instruction_id: int, *, approver: User) -> Instruction:
    """Record one signatory approval, and generate the letter on the last one."""
    instruction = _get(db, instruction_id)
    if instruction.status is not InstructionStatus.PENDING_APPROVAL:
        raise Conflict(
            f"instruction {instruction.reference} is {instruction.status}",
            status=str(instruction.status),
        )
    if approver.role is not UserRole.SIGNATORY:
        raise PermissionDenied(
            "only an authorised signatory may approve an instruction", role=str(approver.role)
        )
    if any(approval.user_id == approver.id for approval in instruction.approvals):
        raise MakerCheckerBreach(
            "the same signatory cannot approve an instruction twice",
            instruction_id=instruction_id,
        )

    db.add(
        InstructionApproval(
            instruction_id=instruction.id,
            user_id=approver.id,
            approved_at=utcnow(),
            created_by=approver.id,
        )
    )
    db.flush()
    db.refresh(instruction)

    required = get_settings().required_signatories
    audit.record(
        db,
        user_id=approver.id,
        action="INSTRUCTION_APPROVED",
        entity="instruction",
        entity_id=instruction.id,
        client_id=instruction.client_id,
        detail={
            "reference": instruction.reference,
            "approvals": len(instruction.approvals),
            "required": required,
        },
    )

    if len(instruction.approvals) >= required:
        instruction.status = InstructionStatus.APPROVED
        letter = letters_svc.render(db, instruction)
        instruction.letter_pdf_sha256 = letter.sha256
        db.flush()
        audit.record(
            db,
            user_id=approver.id,
            action="INSTRUCTION_LETTER_GENERATED",
            entity="instruction",
            entity_id=instruction.id,
            client_id=instruction.client_id,
            detail={"sha256": letter.sha256, "filename": letter.filename},
        )
    return instruction


def reject(db: Session, instruction_id: int, *, user: User, reason: str) -> Instruction:
    instruction = _get(db, instruction_id)
    if instruction.status not in (InstructionStatus.PENDING_APPROVAL, InstructionStatus.APPROVED):
        raise Conflict(
            f"instruction {instruction.reference} is {instruction.status}",
            status=str(instruction.status),
        )
    if user.role is not UserRole.SIGNATORY:
        raise PermissionDenied(
            "only an authorised signatory may reject an instruction", role=str(user.role)
        )
    if not reason.strip():
        raise BusinessRule("a rejection needs a reason")
    return _terminate(db, instruction, InstructionStatus.REJECTED, user.id, reason)


def cancel(db: Session, instruction_id: int, *, user: User, reason: str) -> Instruction:
    instruction = _get(db, instruction_id)
    if instruction.status not in (InstructionStatus.PENDING_APPROVAL, InstructionStatus.APPROVED):
        raise Conflict(
            f"instruction {instruction.reference} is {instruction.status}",
            status=str(instruction.status),
        )
    if not reason.strip():
        raise BusinessRule("a cancellation needs a reason")
    return _terminate(db, instruction, InstructionStatus.CANCELLED, user.id, reason)


def _terminate(
    db: Session, instruction: Instruction, status: InstructionStatus, user_id: str, reason: str
) -> Instruction:
    instruction.status = status
    instruction.rejection_reason = reason
    if instruction.holding_id:
        holding = db.get(Holding, instruction.holding_id)
        if holding is not None and holding.status is HoldingStatus.PENDING:
            holding.status = HoldingStatus.CANCELLED
            holding.updated_by = user_id
    db.flush()
    audit.record(
        db,
        user_id=user_id,
        action=f"INSTRUCTION_{status}",
        entity="instruction",
        entity_id=instruction.id,
        client_id=instruction.client_id,
        detail={"reference": instruction.reference, "reason": reason},
    )
    return instruction


# --- Dispatch and settlement -------------------------------------------------


def mark_sent(
    db: Session,
    instruction_id: int,
    *,
    user_id: str,
    signed_copy_sha256: str,
    signed_copy_blob_id: int | None = None,
) -> Instruction:
    """The wet-signed letter has been scanned and sent to the custodian."""
    instruction = _get(db, instruction_id)
    if instruction.status is not InstructionStatus.APPROVED:
        raise Conflict(
            f"instruction {instruction.reference} is {instruction.status}; only an approved "
            "instruction can be sent",
            status=str(instruction.status),
        )
    if len(instruction.approvals) < get_settings().required_signatories:
        raise MakerCheckerBreach(
            "an instruction cannot be sent without the required signatory approvals",
            approvals=len(instruction.approvals),
        )
    if not signed_copy_sha256:
        raise BusinessRule("the scanned signed letter is required before an instruction is sent")

    instruction.status = InstructionStatus.SENT
    instruction.signed_copy_sha256 = signed_copy_sha256
    instruction.signed_copy_blob_id = signed_copy_blob_id
    instruction.sent_at = utcnow()
    instruction.sent_by = user_id
    db.flush()
    audit.record(
        db,
        user_id=user_id,
        action="INSTRUCTION_SENT",
        entity="instruction",
        entity_id=instruction.id,
        client_id=instruction.client_id,
        detail={
            "reference": instruction.reference,
            "letter_sha256": instruction.letter_pdf_sha256,
            "signed_copy_sha256": signed_copy_sha256,
        },
    )
    return instruction


def settle(
    db: Session,
    instruction_id: int,
    *,
    user_id: str,
    confirmation_ref: str,
    settled_on: date,
    amount: Decimal,
) -> Instruction:
    """The custodian has confirmed the movement.  Only now is anything booked."""
    instruction = _get(db, instruction_id)
    if instruction.status is not InstructionStatus.SENT:
        raise Conflict(
            f"instruction {instruction.reference} is {instruction.status}; only a sent "
            "instruction can be settled",
            status=str(instruction.status),
        )
    if not confirmation_ref.strip():
        raise BusinessRule("the custodian's confirmation reference is required")
    if money(amount) != instruction.amount:
        raise BusinessRule(
            f"the custodian confirmed {money(amount):.2f} but the instruction was for "
            f"{instruction.amount:.2f}; book a new instruction for the difference",
            instructed=f"{instruction.amount:.2f}",
            confirmed=f"{money(amount):.2f}",
        )

    entry = _post_settlement(db, instruction, settled_on=settled_on, user_id=user_id)

    instruction.status = InstructionStatus.SETTLED
    instruction.custodian_confirmation_ref = confirmation_ref
    instruction.settled_at = utcnow()
    instruction.settled_on = settled_on
    instruction.settled_by = user_id
    instruction.journal_entry_id = entry.id
    db.flush()
    audit.record(
        db,
        user_id=user_id,
        action="INSTRUCTION_SETTLED",
        entity="instruction",
        entity_id=instruction.id,
        client_id=instruction.client_id,
        detail={
            "reference": instruction.reference,
            "confirmation_ref": confirmation_ref,
            "settled_on": settled_on.isoformat(),
            "journal_entry_id": entry.id,
        },
    )
    return instruction


def _post_settlement(
    db: Session, instruction: Instruction, *, settled_on: date, user_id: str
) -> JournalEntry:
    client = db.get(Client, instruction.client_id)
    custody = db.get(CustodyAccount, instruction.custody_account_id)
    assert client is not None and custody is not None

    if instruction.type is InstructionType.FX_CONVERSION:
        params = instruction.params or {}
        return fx_svc.convert_currency(
            db,
            client_id=client.id,
            from_account_id=custody.id,
            to_account_id=str(params["target_custody_account_id"]),
            sell=instruction.amount,
            buy=Decimal(str(params["buy_amount"])),
            on=settled_on,
            agreed_rate=Decimal(str(params["agreed_rate"])),
            created_by=user_id,
            instruction_id=instruction.id,
            reference=instruction.reference,
        )

    holding = db.get(Holding, instruction.holding_id) if instruction.holding_id else None
    rule_key = SETTLEMENT_RULES[instruction.type]
    amounts: dict[str, Decimal] = {}
    descriptions: dict[str, str] = {}

    if instruction.type in INVESTMENT_INSTRUCTIONS:
        assert holding is not None
        amounts["amount"] = instruction.amount
        descriptions["amount"] = f"{holding.counterparty} {holding.id}"
    elif instruction.type is InstructionType.PAY_CLIENT_PROFIT:
        gross = instruction.amount
        wht = round_money(gross * client.final_wht_rate)
        amounts = {"gross": gross, "net": money(gross - wht), "wht": wht}
        descriptions = {
            "gross": "Profit paid to client",
            "net": "Paid to client",
            "wht": "Final withholding tax retained",
        }
    else:
        amounts["amount"] = instruction.amount
        descriptions["amount"] = instruction.narrative or str(instruction.type)

    ctx = PostingContext(
        client=client, custody_account=custody, holding=holding, descriptions=descriptions
    )
    lines = build_lines(db, ctx, rule_key, amounts)
    entry = post(
        db,
        entry_date=settled_on,
        event=event_for(rule_key),
        client_id=client.id,
        currency=custody.currency,
        lines=lines,
        narrative=f"{instruction.reference}: {instruction.narrative or instruction.type}",
        reference=instruction.reference,
        instruction_id=instruction.id,
        created_by=user_id,
    )

    if holding is not None and instruction.type in INVESTMENT_INSTRUCTIONS:
        holding.status = HoldingStatus.ACTIVE
        holding.start_date = settled_on
        holding.accrual_start = settled_on
        holding.updated_by = user_id
        db.flush()

    return entry


def _get(db: Session, instruction_id: int) -> Instruction:
    instruction = db.get(Instruction, instruction_id)
    if instruction is None:
        raise NotFound(f"unknown instruction {instruction_id}", instruction_id=instruction_id)
    return instruction


def letter_for(db: Session, instruction_id: int) -> letters_svc.Letter:
    instruction = _get(db, instruction_id)
    if instruction.status is InstructionStatus.PENDING_APPROVAL:
        raise Conflict(
            "the letter is generated when the instruction is fully approved",
            status=str(instruction.status),
        )
    return letters_svc.render(db, instruction)


def awaiting(db: Session, user: User) -> list[Instruction]:
    """The instructions this user can act on right now."""
    if user.role is UserRole.SIGNATORY:
        rows = db.execute(
            select(Instruction)
            .where(Instruction.status == InstructionStatus.PENDING_APPROVAL)
            .order_by(Instruction.value_date, Instruction.id)
        ).scalars()
        return [
            row for row in rows if all(approval.user_id != user.id for approval in row.approvals)
        ]
    if user.role in (UserRole.MAKER, UserRole.FINANCE):
        return list(
            db.execute(
                select(Instruction)
                .where(Instruction.status.in_([InstructionStatus.APPROVED, InstructionStatus.SENT]))
                .order_by(Instruction.value_date, Instruction.id)
            ).scalars()
        )
    return []


__all__ = [
    "ZERO",
    "AssetClass",
    "CashPosition",
    "Check",
    "approve",
    "awaiting",
    "cancel",
    "cash_position",
    "create",
    "gate_checks",
    "letter_for",
    "mark_sent",
    "next_reference",
    "reject",
    "settle",
]
