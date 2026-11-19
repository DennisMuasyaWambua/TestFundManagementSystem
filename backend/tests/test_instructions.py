"""The instruction lifecycle rules, and the letter that goes with them."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from app.errors import (
    BusinessRule,
    Conflict,
    InsufficientCash,
    MakerCheckerBreach,
    OnboardingIncomplete,
    PermissionDenied,
)
from app.models import (
    HoldingStatus,
    Instruction,
    InstructionStatus,
    InstructionType,
    KycStatus,
    User,
)
from app.services import instructions as ins
from app.services import letters as letters_svc
from app.services import receipts
from sqlalchemy.orm import Session

from tests.conftest import add_client

CLIENT = "INSC"
CUSTODY = f"{CLIENT}-CUST"
VALUE_DATE = date(2026, 3, 2)

WAKALA_PARAMS = {
    "holding_id": "FD-INSC-01",
    "counterparty": "Absa Bank Kenya PLC",
    "profit_rate": "0.0425",
    "day_basis": 365,
    "maturity_date": "2026-09-01",
    "shariah_cert_ref": "SSB/2026/100",
}


def user(db: Session, user_id: str) -> User:
    row = db.get(User, user_id)
    assert row is not None
    return row


def funded(db: Session, amount: str = "1000000.00") -> None:
    add_client(db, CLIENT)
    receipts.record_contribution(
        db,
        client_id=CLIENT,
        custody_account_id=CUSTODY,
        amount=Decimal(amount),
        value_date=date(2026, 3, 1),
        advice_ref="CR-1",
        created_by="ops.maker",
    )


def raise_wakala(db: Session, amount: str = "500000.00", **overrides: object) -> Instruction:
    params = dict(WAKALA_PARAMS)
    params.update(overrides)  # type: ignore[arg-type]
    return ins.create(
        db,
        client_id=CLIENT,
        custody_account_id=CUSTODY,
        instruction_type=InstructionType.PLACE_WAKALA,
        amount=Decimal(amount),
        value_date=VALUE_DATE,
        maker_id="ops.maker",
        beneficiary="Absa Bank Kenya PLC",
        params=params,
    )


def test_references_are_gap_free_per_year(seeded: Session) -> None:
    assert ins.next_reference(seeded, 2026) == "INS/2026/0001"
    assert ins.next_reference(seeded, 2026) == "INS/2026/0002"
    assert ins.next_reference(seeded, 2027) == "INS/2027/0001"
    assert ins.next_reference(seeded, 2026) == "INS/2026/0003"


def test_creation_requires_a_complete_onboarding_gate(seeded: Session) -> None:
    client = add_client(seeded, CLIENT)
    client.kyc_status = KycStatus.PENDING
    seeded.flush()
    with pytest.raises(OnboardingIncomplete, match="KYC"):
        raise_wakala(seeded, "1.00")

    client.kyc_status = KycStatus.APPROVED
    client.agreement_ref = None
    seeded.flush()
    with pytest.raises(OnboardingIncomplete, match="agreement"):
        raise_wakala(seeded, "1.00")


def test_creation_requires_the_custody_appointment(seeded: Session) -> None:
    add_client(seeded, CLIENT)
    from app.models import CustodyAccount

    account = seeded.get(CustodyAccount, CUSTODY)
    assert account is not None
    account.custody_agreement_ref = None
    seeded.flush()
    with pytest.raises(OnboardingIncomplete, match="Custodian appointed"):
        raise_wakala(seeded, "1.00")


def test_cash_available_counts_the_pipeline(seeded: Session) -> None:
    funded(seeded, "1000000.00")
    raise_wakala(seeded, "700000.00")
    with pytest.raises(InsufficientCash):
        raise_wakala(seeded, "400000.00", holding_id="FD-INSC-02")
    # what is left is still available
    raise_wakala(seeded, "300000.00", holding_id="FD-INSC-03")


def test_investment_instructions_need_their_deal_terms(seeded: Session) -> None:
    funded(seeded)
    with pytest.raises(BusinessRule, match="Shariah"):
        raise_wakala(seeded, "1000.00", shariah_cert_ref="")
    with pytest.raises(BusinessRule, match="Deal terms"):
        raise_wakala(seeded, "1000.00", profit_rate="")


def test_payouts_need_the_clients_written_request(seeded: Session) -> None:
    funded(seeded)
    with pytest.raises(BusinessRule, match="written request"):
        ins.create(
            seeded,
            client_id=CLIENT,
            custody_account_id=CUSTODY,
            instruction_type=InstructionType.RETURN_CAPITAL,
            amount=Decimal("1000.00"),
            value_date=VALUE_DATE,
            maker_id="ops.maker",
            beneficiary=f"{CLIENT} Test Mandate",
        )
    ins.create(
        seeded,
        client_id=CLIENT,
        custody_account_id=CUSTODY,
        instruction_type=InstructionType.RETURN_CAPITAL,
        amount=Decimal("1000.00"),
        value_date=VALUE_DATE,
        maker_id="ops.maker",
        beneficiary=f"{CLIENT} Test Mandate",
        client_instruction_ref="CLIENT-LETTER-2026-03-01",
    )


def test_profit_payout_cannot_exceed_profit_owed(seeded: Session) -> None:
    funded(seeded)
    with pytest.raises(BusinessRule, match="Profit owed"):
        ins.create(
            seeded,
            client_id=CLIENT,
            custody_account_id=CUSTODY,
            instruction_type=InstructionType.PAY_CLIENT_PROFIT,
            amount=Decimal("100.00"),
            value_date=VALUE_DATE,
            maker_id="ops.maker",
            beneficiary=f"{CLIENT} Test Mandate",
            client_instruction_ref="CLIENT-LETTER-1",
        )


def test_maker_cannot_approve_and_a_signatory_cannot_sign_twice(seeded: Session) -> None:
    funded(seeded)
    instruction = raise_wakala(seeded)

    maker_as_signatory = user(seeded, "ops.maker")
    with pytest.raises(PermissionDenied):
        ins.approve(seeded, instruction.id, approver=maker_as_signatory)

    ins.approve(seeded, instruction.id, approver=user(seeded, "sig.one"))
    with pytest.raises(MakerCheckerBreach, match="twice"):
        ins.approve(seeded, instruction.id, approver=user(seeded, "sig.one"))

    with pytest.raises(PermissionDenied):
        ins.approve(seeded, instruction.id, approver=user(seeded, "admin"))

    ins.approve(seeded, instruction.id, approver=user(seeded, "sig.two"))
    seeded.refresh(instruction)
    assert instruction.status is InstructionStatus.APPROVED
    assert instruction.letter_pdf_sha256 is not None


def test_a_signatory_who_is_the_maker_can_approve_their_own(seeded: Session) -> None:
    """This test system does not restrict a signatory from approving a
    deal they themselves prepared -- see opening_balances/closing/
    instructions for where that was deliberately relaxed."""
    funded(seeded)
    instruction = ins.create(
        seeded,
        client_id=CLIENT,
        custody_account_id=CUSTODY,
        instruction_type=InstructionType.PLACE_WAKALA,
        amount=Decimal("1000.00"),
        value_date=VALUE_DATE,
        maker_id="sig.one",
        params=WAKALA_PARAMS,
    )
    ins.approve(seeded, instruction.id, approver=user(seeded, "sig.one"))
    seeded.refresh(instruction)
    assert len(instruction.approvals) == 1


def test_sending_needs_two_approvals_and_a_scan(seeded: Session) -> None:
    funded(seeded)
    instruction = raise_wakala(seeded)
    with pytest.raises(Conflict):
        ins.mark_sent(seeded, instruction.id, user_id="ops.maker", signed_copy_sha256="a" * 64)
    ins.approve(seeded, instruction.id, approver=user(seeded, "sig.one"))
    with pytest.raises(Conflict):
        ins.mark_sent(seeded, instruction.id, user_id="ops.maker", signed_copy_sha256="a" * 64)
    ins.approve(seeded, instruction.id, approver=user(seeded, "sig.two"))
    with pytest.raises(BusinessRule, match="scanned signed letter"):
        ins.mark_sent(seeded, instruction.id, user_id="ops.maker", signed_copy_sha256="")
    ins.mark_sent(seeded, instruction.id, user_id="ops.maker", signed_copy_sha256="a" * 64)
    seeded.refresh(instruction)
    assert instruction.status is InstructionStatus.SENT


def test_settlement_requires_sent_and_the_exact_amount(seeded: Session) -> None:
    funded(seeded)
    instruction = raise_wakala(seeded)
    with pytest.raises(Conflict, match="only a sent"):
        ins.settle(
            seeded,
            instruction.id,
            user_id="fin.head",
            confirmation_ref="CONF",
            settled_on=VALUE_DATE,
            amount=Decimal("500000.00"),
        )
    ins.approve(seeded, instruction.id, approver=user(seeded, "sig.one"))
    ins.approve(seeded, instruction.id, approver=user(seeded, "sig.two"))
    ins.mark_sent(seeded, instruction.id, user_id="ops.maker", signed_copy_sha256="a" * 64)

    with pytest.raises(BusinessRule, match="confirmed"):
        ins.settle(
            seeded,
            instruction.id,
            user_id="fin.head",
            confirmation_ref="CONF",
            settled_on=VALUE_DATE,
            amount=Decimal("499999.00"),
        )
    with pytest.raises(BusinessRule, match="confirmation reference"):
        ins.settle(
            seeded,
            instruction.id,
            user_id="fin.head",
            confirmation_ref="  ",
            settled_on=VALUE_DATE,
            amount=Decimal("500000.00"),
        )

    ins.settle(
        seeded,
        instruction.id,
        user_id="fin.head",
        confirmation_ref="ABSA-CONF-77",
        settled_on=VALUE_DATE,
        amount=Decimal("500000.00"),
    )
    seeded.refresh(instruction)
    assert instruction.status is InstructionStatus.SETTLED
    assert instruction.journal_entry_id is not None

    from app.models import Holding

    holding = seeded.get(Holding, "FD-INSC-01")
    assert holding is not None
    assert holding.status is HoldingStatus.ACTIVE
    assert holding.start_date == VALUE_DATE
    assert holding.accrual_start == VALUE_DATE


def test_nothing_is_booked_before_the_custodian_confirms(seeded: Session) -> None:
    from app.ledger import balances

    funded(seeded)
    instruction = raise_wakala(seeded)
    ins.approve(seeded, instruction.id, approver=user(seeded, "sig.one"))
    ins.approve(seeded, instruction.id, approver=user(seeded, "sig.two"))
    ins.mark_sent(seeded, instruction.id, user_id="ops.maker", signed_copy_sha256="a" * 64)
    # approved and sent, but not settled: the ledger has only the contribution
    assert balances.balance(seeded, client_id=CLIENT, account_code="1150") == Decimal("1000000.00")
    assert balances.balance(seeded, client_id=CLIENT, account_code="1220") == Decimal("0.00")


def test_rejection_cancels_the_pending_holding(seeded: Session) -> None:
    from app.models import Holding

    funded(seeded)
    instruction = raise_wakala(seeded)
    ins.reject(seeded, instruction.id, user=user(seeded, "sig.one"), reason="terms not agreed")
    seeded.refresh(instruction)
    assert instruction.status is InstructionStatus.REJECTED
    holding = seeded.get(Holding, "FD-INSC-01")
    assert holding is not None and holding.status is HoldingStatus.CANCELLED


def test_letter_bytes_and_hash_are_reproducible(seeded: Session) -> None:
    funded(seeded)
    instruction = raise_wakala(seeded)
    ins.approve(seeded, instruction.id, approver=user(seeded, "sig.one"))
    ins.approve(seeded, instruction.id, approver=user(seeded, "sig.two"))
    seeded.refresh(instruction)

    first = letters_svc.render(seeded, instruction)
    second = letters_svc.render(seeded, instruction)
    assert first.pdf == second.pdf
    assert first.sha256 == second.sha256
    assert instruction.letter_pdf_sha256 == first.sha256
    assert first.pdf.startswith(b"%PDF")


def test_letter_names_the_client_the_agreements_and_the_two_signatories(
    seeded: Session,
) -> None:
    funded(seeded)
    instruction = raise_wakala(seeded)
    ins.approve(seeded, instruction.id, approver=user(seeded, "sig.one"))
    ins.approve(seeded, instruction.id, approver=user(seeded, "sig.two"))
    seeded.refresh(instruction)
    letter = letters_svc.render(seeded, instruction)

    text = _pdf_text(letter.pdf)
    assert "PLACEMENT OF WAKALA DEPOSIT" in text
    assert "two authorised signatories" in text
    assert "client funds held in trust" in text
    assert "INS/2026/0001" in text
    assert "SSB/2026/100" in text
    assert "interest" not in text.lower()


def _pdf_text(pdf: bytes) -> str:
    """Extract the text of a ReportLab PDF without pulling in a parser dependency.

    ReportLab writes page content as ASCII85 then Flate, so both layers are peeled
    before the text-showing operators are read off.
    """
    import base64
    import contextlib
    import re
    import zlib

    chunks: list[str] = []
    for match in re.finditer(rb"stream(.*?)endstream", pdf, re.S):
        raw = match.group(1).strip(b"\r\n")
        with contextlib.suppress(ValueError):
            raw = base64.a85decode(raw, adobe=True)
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            continue
        for piece in re.findall(rb"\((?:[^()\\]|\\.)*\)", raw, re.S):
            chunks.append(piece[1:-1].decode("latin-1"))
    text = " ".join(chunks)
    for escaped, plain in (("\\(", "("), ("\\)", ")"), ("\\\\", "\\")):
        text = text.replace(escaped, plain)
    return text
