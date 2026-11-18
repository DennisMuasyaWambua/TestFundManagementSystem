"""Instruction letters as PDF.

The bytes are deterministic: ReportLab runs in invariant mode and every value on the
page comes from the instruction, never from the clock.  That is what makes the stored
SHA-256 meaningful -- regenerating the letter for the same approved instruction
produces a byte-identical file whose hash matches what was recorded at approval.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import NotFound
from app.models import Client, CustodyAccount, Holding, Instruction, InstructionType, User
from app.money import fmt, fmt_rate

TYPE_SUBJECTS: dict[InstructionType, str] = {
    InstructionType.PLACE_WAKALA: "PLACEMENT OF WAKALA DEPOSIT",
    InstructionType.BUY_SUKUK: "PURCHASE OF SUKUK",
    InstructionType.DISBURSE_FINANCING: "DISBURSEMENT OF PRIVATE FINANCING",
    InstructionType.PURCHASE_PROPERTY: "PURCHASE OF INVESTMENT PROPERTY",
    InstructionType.PAY_CLIENT_PROFIT: "PAYMENT OF PROFIT TO CLIENT",
    InstructionType.RETURN_CAPITAL: "RETURN OF CAPITAL TO CLIENT",
    InstructionType.PAY_MGMT_FEE: "PAYMENT OF MANAGEMENT FEE",
    InstructionType.PAY_CUSTODY_FEE: "PAYMENT OF CUSTODY FEE",
    InstructionType.FX_CONVERSION: "CURRENCY CONVERSION",
}

TRUST_STATEMENT = (
    "The funds held in the account referred to above are client funds held in trust. "
    "They are not the assets of the fund manager and may not be applied for the benefit "
    "of any other client or of the fund manager."
)


@dataclass(frozen=True)
class SignatureBlock:
    name: str
    title: str
    approved_at: str


@dataclass(frozen=True)
class Letter:
    pdf: bytes
    sha256: str
    filename: str


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "firm": ParagraphStyle(
            "firm", parent=base["Heading1"], fontSize=15, leading=18, spaceAfter=2
        ),
        "firmline": ParagraphStyle(
            "firmline",
            parent=base["Normal"],
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor("#5B6470"),
        ),
        "body": ParagraphStyle(
            "body",
            parent=base["Normal"],
            fontSize=9.5,
            leading=13,
            alignment=TA_JUSTIFY,
            spaceAfter=6,
        ),
        "subject": ParagraphStyle(
            "subject",
            parent=base["Normal"],
            fontSize=10,
            leading=13,
            spaceAfter=8,
            fontName="Helvetica-Bold",
        ),
        "small": ParagraphStyle(
            "small",
            parent=base["Normal"],
            fontSize=7.5,
            leading=10,
            textColor=colors.HexColor("#5B6470"),
        ),
        "cell": ParagraphStyle("cell", parent=base["Normal"], fontSize=8.5, leading=11),
        "cellb": ParagraphStyle(
            "cellb", parent=base["Normal"], fontSize=8.5, leading=11, fontName="Helvetica-Bold"
        ),
        "warn": ParagraphStyle(
            "warn",
            parent=base["Normal"],
            fontSize=9,
            leading=12,
            fontName="Helvetica-Bold",
            spaceBefore=4,
            spaceAfter=8,
        ),
    }


def detail_rows(
    db: Session,
    instruction: Instruction,
    *,
    client: Client,
    custody: CustodyAccount,
    holding: Holding | None,
) -> list[tuple[str, str]]:
    """The details table: only the rows that apply to this instruction type."""
    params = instruction.params or {}
    rows: list[tuple[str, str]] = [
        ("Client", client.legal_name),
        ("Custody account", f"{custody.account_number} ({custody.currency})"),
        ("Amount", f"{instruction.currency} {fmt(instruction.amount)}"),
        ("Value date", instruction.value_date.isoformat()),
    ]
    if instruction.beneficiary:
        rows.append(("Pay to", instruction.beneficiary))
    if instruction.beneficiary_account:
        rows.append(("Beneficiary account", instruction.beneficiary_account))
    if holding is not None:
        rows.append(("Counterparty", holding.counterparty))
        if holding.profit_rate is not None:
            rows.append(
                ("Expected profit rate", f"{fmt_rate(holding.profit_rate * 100)}% per annum")
            )
            rows.append(("Day basis", f"{holding.day_basis} days"))
        if holding.nominal is not None:
            rows.append(("Nominal value", f"{holding.currency} {fmt(holding.nominal)}"))
        if holding.maturity_date is not None:
            rows.append(("Maturity date", holding.maturity_date.isoformat()))
        if holding.monthly_rent is not None:
            rows.append(
                ("Expected monthly rent", f"{holding.currency} {fmt(holding.monthly_rent)}")
            )
        rows.append(("Deal reference", holding.id))
        rows.append(("Shariah approval", holding.shariah_cert_ref or "-"))
    if instruction.type is InstructionType.FX_CONVERSION:
        target_id = str(params.get("target_custody_account_id", ""))
        target = db.get(CustodyAccount, target_id) if target_id else None
        rows.append(("Sell", f"{instruction.currency} {fmt(instruction.amount)}"))
        rows.append(
            (
                "Buy",
                f"{target.currency if target else params.get('buy_currency', '')} "
                f"{fmt(Decimal(str(params.get('buy_amount', '0'))))}",
            )
        )
        rows.append(("Agreed rate", fmt_rate(Decimal(str(params.get("agreed_rate", "0"))))))
        if target is not None:
            rows.append(("Credit account", f"{target.account_number} ({target.currency})"))
    if instruction.type is InstructionType.PAY_CLIENT_PROFIT:
        rows.append(("Gross profit", f"{instruction.currency} {fmt(instruction.amount)}"))
        rows.append(
            (
                "Withholding tax",
                f"{instruction.currency} {fmt(Decimal(str(params.get('wht', '0'))))}",
            )
        )
        net = Decimal(str(params.get("net", instruction.amount)))
        rows.append(("Net payable", f"{instruction.currency} {fmt(net)}"))
    if instruction.client_instruction_ref:
        rows.append(("Client's written request", instruction.client_instruction_ref))
    return rows


def signature_blocks(db: Session, instruction: Instruction) -> list[SignatureBlock]:
    blocks: list[SignatureBlock] = []
    for approval in instruction.approvals:
        user = db.get(User, approval.user_id)
        blocks.append(
            SignatureBlock(
                name=user.name if user else approval.user_id,
                title=user.title if user else "Authorised signatory",
                approved_at=approval.approved_at.strftime("%Y-%m-%d %H:%M UTC"),
            )
        )
    return blocks


def render(db: Session, instruction: Instruction, *, letter_date: date | None = None) -> Letter:
    """Build the instruction letter.  Same instruction in, same bytes out."""
    settings = get_settings()
    client = db.get(Client, instruction.client_id)
    custody = db.get(CustodyAccount, instruction.custody_account_id)
    if client is None or custody is None:
        raise NotFound(
            f"instruction {instruction.reference} is missing its client or custody account",
            instruction_id=instruction.id,
        )
    holding = db.get(Holding, instruction.holding_id) if instruction.holding_id else None
    blocks = signature_blocks(db, instruction)
    on = letter_date or (
        max(a.approved_at.date() for a in instruction.approvals)
        if instruction.approvals
        else instruction.value_date
    )

    styles = _styles()
    from io import BytesIO

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"{instruction.reference} {TYPE_SUBJECTS[instruction.type]}",
        author=settings.firm_name,
        subject=f"Custody instruction {instruction.reference}",
        creator=settings.firm_name,
        invariant=1,
    )

    story: list[object] = [
        Paragraph(settings.firm_name, styles["firm"]),
        Paragraph(settings.firm_address, styles["firmline"]),
        Paragraph(settings.firm_contact, styles["firmline"]),
        Paragraph(
            "Licensed by the Capital Markets Authority - "
            f"Licence No. {settings.cma_licence_number}",
            styles["firmline"],
        ),
        Spacer(1, 4 * mm),
        HRFlowable(width="100%", thickness=0.7, color=colors.HexColor("#0E6B57")),
        Spacer(1, 5 * mm),
    ]

    header = Table(
        [
            [
                Paragraph(f"Date: <b>{on.isoformat()}</b>", styles["cell"]),
                Paragraph(f"Our reference: <b>{instruction.reference}</b>", styles["cell"]),
            ]
        ],
        colWidths=[85 * mm, 85 * mm],
    )
    header.setStyle(
        TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (1, 0), (1, 0), "RIGHT")])
    )
    story.append(header)
    story.append(Spacer(1, 5 * mm))

    story.append(Paragraph(custody.custodian_contact, styles["cell"]))
    story.append(Paragraph(f"<b>{custody.custodian}</b>", styles["cell"]))
    for part in custody.custodian_address.split("\n"):
        story.append(Paragraph(part, styles["cell"]))
    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph("Dear Sir / Madam,", styles["body"]))

    subject = (
        f"RE: {TYPE_SUBJECTS[instruction.type]} &ndash; "
        f"{instruction.currency} {fmt(instruction.amount)}"
    )
    story.append(Paragraph(subject, styles["subject"]))

    story.append(
        Paragraph(
            f"We act as investment manager for <b>{client.legal_name}</b> under investment "
            f"management agreement reference {client.agreement_ref or '-'}, and you hold that "
            f"client's assets under custody agreement reference "
            f"{custody.custody_agreement_ref or '-'}. In accordance with that appointment we "
            f"hereby instruct you to debit custody account {custody.account_number} "
            f"({custody.currency}) with {instruction.currency} {fmt(instruction.amount)} with "
            f"value {instruction.value_date.isoformat()} and to apply it as set out below.",
            styles["body"],
        )
    )
    if instruction.narrative:
        story.append(Paragraph(instruction.narrative, styles["body"]))

    rows = detail_rows(db, instruction, client=client, custody=custody, holding=holding)
    table = Table(
        [
            [Paragraph(label, styles["cell"]), Paragraph(value, styles["cellb"])]
            for label, value in rows
        ],
        colWidths=[55 * mm, 115 * mm],
    )
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#E3E6EA")),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F6F7F9")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 5 * mm))

    story.append(
        Paragraph(
            "Please do not act on this instruction unless it is signed by two authorised "
            "signatories of this firm whose specimen signatures you hold.",
            styles["warn"],
        )
    )
    story.append(Paragraph("Yours faithfully,", styles["body"]))
    story.append(Spacer(1, 2 * mm))

    while len(blocks) < 2:
        blocks.append(SignatureBlock(name="", title="Authorised signatory", approved_at=""))
    signature_cells = [
        [
            Paragraph(
                "<br/><br/>______________________________<br/>"
                f"<b>{block.name or '&nbsp;'}</b><br/>{block.title}<br/>"
                f"<font size=7 color='#5B6470'>Approved in system: "
                f"{block.approved_at or 'pending'}</font>",
                styles["cell"],
            )
            for block in blocks[:2]
        ]
    ]
    signatures = Table(signature_cells, colWidths=[85 * mm, 85 * mm])
    signatures.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(KeepTogether(signatures))
    story.append(Spacer(1, 6 * mm))
    story.append(HRFlowable(width="100%", thickness=0.4, color=colors.HexColor("#E3E6EA")))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(TRUST_STATEMENT, styles["small"]))
    story.append(
        Paragraph(
            f"Instruction reference {instruction.reference} &middot; {settings.firm_name} "
            f"&middot; CMA Licence No. {settings.cma_licence_number}",
            styles["small"],
        )
    )

    doc.build(story)
    pdf = buffer.getvalue()
    return Letter(
        pdf=pdf,
        sha256=hashlib.sha256(pdf).hexdigest(),
        filename=f"{instruction.reference.replace('/', '-')}.pdf",
    )
