"""Client statement as PDF, and the portfolio summary as a spreadsheet.

The statement shows Section A (what the client is owed) beside Section B (where that
money is held) and states plainly whether the two agree.  If they do not, or if
anything is sitting in suspense, the statement carries a held banner instead of a
clean A = B confirmation -- it is never quietly sent out.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from io import BytesIO

from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy.orm import Session

from app.config import get_settings
from app.money import fmt, fmt_rate
from app.services import reports as reports_svc
from app.services.letters import TRUST_STATEMENT

ACCENT = colors.HexColor("#0E6B57")
BORDER = colors.HexColor("#E3E6EA")
MUTED = colors.HexColor("#5B6470")
WARN_BG = colors.HexColor("#FDF2DF")
WARN_FG = colors.HexColor("#7A4700")
OK_BG = colors.HexColor("#E3F3EE")


@dataclass(frozen=True)
class RenderedStatement:
    pdf: bytes
    sha256: str
    filename: str


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "h1": ParagraphStyle("h1", parent=base["Heading1"], fontSize=15, leading=18, spaceAfter=2),
        "h2": ParagraphStyle(
            "h2", parent=base["Heading2"], fontSize=10.5, leading=13, spaceBefore=6, spaceAfter=4
        ),
        "body": ParagraphStyle("body", parent=base["Normal"], fontSize=9, leading=12),
        "muted": ParagraphStyle(
            "muted", parent=base["Normal"], fontSize=8, leading=11, textColor=MUTED
        ),
        "cell": ParagraphStyle("cell", parent=base["Normal"], fontSize=8.5, leading=11),
        "cellb": ParagraphStyle(
            "cellb", parent=base["Normal"], fontSize=8.5, leading=11, fontName="Helvetica-Bold"
        ),
        "banner": ParagraphStyle(
            "banner", parent=base["Normal"], fontSize=9, leading=12, textColor=WARN_FG
        ),
    }


def _money_table(rows: list[tuple[str, str]], styles: dict[str, ParagraphStyle]) -> Table:
    table = Table(
        [
            [Paragraph(label, styles["cell"]), Paragraph(value, styles["cellb"])]
            for label, value in rows
        ],
        colWidths=[55 * mm, 27 * mm],
    )
    table.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (0, 0), (-1, -2), 0.3, BORDER),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return table


def render(db: Session, client_id: str, *, from_date: date, to_date: date) -> RenderedStatement:
    statement = reports_svc.client_statement(db, client_id, from_date=from_date, to_date=to_date)
    settings = get_settings()
    styles = _styles()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=f"Client statement {client_id} {to_date.isoformat()}",
        author=settings.firm_name,
        subject="Client statement",
        creator=settings.firm_name,
        invariant=1,
    )

    story: list[object] = [
        Paragraph(settings.firm_name, styles["h1"]),
        Paragraph(
            f"Licensed by the Capital Markets Authority - Licence No. "
            f"{settings.cma_licence_number}",
            styles["muted"],
        ),
        Spacer(1, 3 * mm),
        HRFlowable(width="100%", thickness=0.7, color=ACCENT),
        Spacer(1, 4 * mm),
        Paragraph("<b>CLIENT STATEMENT</b>", styles["h2"]),
        Paragraph(
            f"<b>{statement.client}</b><br/>Reporting currency {statement.currency}<br/>"
            f"Period {from_date.isoformat()} to {to_date.isoformat()}",
            styles["body"],
        ),
        Spacer(1, 4 * mm),
    ]

    if statement.held_reason:
        banner = Table(
            [[Paragraph(f"<b>Statement held.</b> {statement.held_reason}", styles["banner"])]],
            colWidths=[178 * mm],
        )
        banner.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), WARN_BG),
                    ("BOX", (0, 0), (-1, -1), 0.5, WARN_FG),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
    else:
        banner = Table(
            [
                [
                    Paragraph(
                        f"<b>A = B.</b> Your account balance of {statement.currency} "
                        f"{fmt(statement.your_account.your_balance)} is matched by assets "
                        "held with the custodian.",
                        styles["body"],
                    )
                ]
            ],
            colWidths=[178 * mm],
        )
        banner.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), OK_BG),
                    ("BOX", (0, 0), (-1, -1), 0.5, ACCENT),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
    story.append(banner)
    story.append(Spacer(1, 5 * mm))

    account = statement.your_account
    section_a = _money_table(
        [
            ("Capital brought forward", fmt(account.capital_brought_forward)),
            ("Capital paid in and returned", fmt(account.capital_movements)),
            ("Profit brought forward", fmt(account.profit_brought_forward)),
            ("Profit earned in closed periods", fmt(account.profit_earned_closed)),
            ("Profit paid to you", f"({fmt(account.profit_paid)})"),
            ("Profit earned, period not yet closed", fmt(account.profit_open_period)),
            ("Of which management fees charged", f"({fmt(account.fees_charged)})"),
            ("Your balance", fmt(account.your_balance)),
        ],
        styles,
    )

    held = statement.where_held
    where_rows = [(f"{line.code} {line.name}", fmt(line.amount)) for line in held.assets]
    where_rows += [
        (f"Less {line.code} {line.name}", f"({fmt(line.amount)})") for line in held.less_payables
    ]
    where_rows.append(("Net assets held", fmt(held.net_holdings)))
    section_b = _money_table(where_rows, styles)

    columns = Table(
        [
            [
                Paragraph("<b>A. Your account with us</b>", styles["h2"]),
                Paragraph("<b>B. Where your money is held</b>", styles["h2"]),
            ],
            [section_a, section_b],
        ],
        colWidths=[89 * mm, 89 * mm],
    )
    columns.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(columns)
    story.append(Spacer(1, 6 * mm))

    story.append(Paragraph("<b>Your investments</b>", styles["h2"]))
    if statement.holdings:
        header = [
            "Deal",
            "Type",
            "Ccy",
            "Outstanding",
            "Accrued profit",
            "Fair value adj.",
            "Profit rate",
            "Maturity",
        ]
        data = [[Paragraph(f"<b>{column}</b>", styles["cell"]) for column in header]]
        for holding in statement.holdings:
            data.append(
                [
                    Paragraph(holding.id, styles["cell"]),
                    Paragraph(holding.asset_class.replace("_", " ").title(), styles["cell"]),
                    Paragraph(holding.currency, styles["cell"]),
                    Paragraph(fmt(holding.outstanding), styles["cell"]),
                    Paragraph(fmt(holding.accrued_profit), styles["cell"]),
                    Paragraph(fmt(holding.fair_value_adjustment), styles["cell"]),
                    Paragraph(
                        "-"
                        if holding.profit_rate is None
                        else f"{fmt_rate(holding.profit_rate * 100)}%",
                        styles["cell"],
                    ),
                    Paragraph(
                        "-" if holding.maturity_date is None else holding.maturity_date.isoformat(),
                        styles["cell"],
                    ),
                ]
            )
        table = Table(
            data, colWidths=[26 * mm, 26 * mm, 12 * mm, 26 * mm, 26 * mm, 24 * mm, 20 * mm, 22 * mm]
        )
        table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.3, BORDER),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F6F7F9")),
                    ("ALIGN", (3, 1), (6, -1), "RIGHT"),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        story.append(table)
    else:
        story.append(Paragraph("No investments were held in this period.", styles["muted"]))

    story.append(Spacer(1, 6 * mm))
    story.append(HRFlowable(width="100%", thickness=0.4, color=BORDER))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(TRUST_STATEMENT, styles["muted"]))
    story.append(
        Paragraph(
            "Profit is earned on Shariah-compliant assets only. This statement reports "
            "profit, not interest.",
            styles["muted"],
        )
    )

    doc.build(story)
    pdf = buffer.getvalue()
    return RenderedStatement(
        pdf=pdf,
        sha256=hashlib.sha256(pdf).hexdigest(),
        filename=f"statement-{client_id}-{to_date.isoformat()}.pdf",
    )


def portfolio_summary_xlsx(db: Session, *, as_of: date, client_id: str | None = None) -> bytes:
    """The CMA portfolio report as a spreadsheet (Licensing Regs 2025, reg 40(1))."""
    summary = reports_svc.portfolio_summary(db, as_of=as_of, client_id=client_id)
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "Portfolio summary"
    sheet.append(["Portfolio summary as at", as_of.isoformat()])
    sheet.append(["Number of clients", summary.number_of_clients])
    sheet.append([])
    sheet.append(
        ["Client", "Mandate", "Asset class", "Deals", "Cost", "Fair value", "Accrued profit"]
    )
    for row in summary.rows:
        sheet.append(
            [
                row.client_id,
                row.client,
                row.asset_class,
                row.count,
                fmt(row.cost),
                fmt(row.fair_value),
                fmt(row.accrued_profit),
            ]
        )
    sheet.append([])
    sheet.append(["Client", "Custodian", "Account", "Currency", "Balance", "Base amount"])
    for cash in summary.cash:
        sheet.append(
            [
                cash.client_id,
                cash.custodian,
                cash.account_number,
                cash.currency,
                fmt(cash.balance),
                fmt(cash.base_amount),
            ]
        )
    sheet.append([])
    for key, value in summary.totals.items():
        sheet.append([key.replace("_", " ").title(), fmt(value)])

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
