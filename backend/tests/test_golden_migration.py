"""Golden numbers G1 and G2: the two go-live opening balance batches.

G1  Rayan, cutover 31 January 2026: debits = credits = 5,619,061.17; the client
    statement shows A = B = 5,490,667.23; the cash reconciliation against Absa's
    10,710.53 matches.
G2  Taaj: debits = credits = 7,614,827.62; suspense (1390) carries 516,745.92;
    A = 7,498,198.90 and the statement is flagged as held.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from app.errors import BusinessRule
from app.models import BatchStatus, Holding, HoldingStatus, User
from app.services import opening_balances as ob
from app.services import reports
from sqlalchemy.orm import Session

from tests.conftest import balance_of

SEED = Path(__file__).resolve().parents[1] / "seed" / "opening_balances"
CUTOVER = date(2026, 1, 31)


def load(db: Session, client_id: str, folder: str, *, pro_rata: bool = False) -> object:
    batch = ob.create_batch(
        db,
        client_id=client_id,
        cutover_date=CUTOVER,
        prepared_by="fin.officer",
        pro_rata_accrual_split=pro_rata,
    )
    base = SEED / folder
    ob.load_holdings(db, batch, (base / "holdings.csv").read_text(encoding="utf-8"))
    ob.load_lines(db, batch, (base / "lines.csv").read_text(encoding="utf-8"))
    ob.load_custodian_rows(
        db, batch, (base / "custodian_balances.csv").read_text(encoding="utf-8"), kind="BALANCE"
    )
    ob.load_custodian_rows(
        db, batch, (base / "custodian_positions.csv").read_text(encoding="utf-8"), kind="POSITION"
    )
    return batch


def approver(db: Session, user_id: str = "fin.head") -> User:
    user = db.get(User, user_id)
    assert user is not None
    return user


# --- G1 ----------------------------------------------------------------------


@pytest.mark.golden
def test_g1_rayan_opening_batch(seeded: Session) -> None:
    batch = load(seeded, "RAYAN", "rayan", pro_rata=True)
    report = ob.validate(seeded, batch)  # type: ignore[arg-type]

    assert report.ok, [f.message for f in report.errors]
    assert report.totals["debits"] == "5619061.17"
    assert report.totals["credits"] == "5619061.17"
    assert report.totals["section_a"] == "5490667.23"
    assert report.totals["section_b"] == "5490667.23"

    codes = {finding.code for finding in report.warnings}
    assert "PRO_RATA_ACCRUAL_PLACEHOLDER" in codes
    assert "ACCRUAL_OUT_OF_TOLERANCE" in codes

    preview = ob.preview(seeded, batch)  # type: ignore[arg-type]
    assert preview.total_debit == Decimal("5619061.17")
    assert preview.total_credit == Decimal("5619061.17")
    assert preview.balanced and preview.reconciles
    assert sum(1 for line in preview.lines if line.derived) == 7

    ob.acknowledge_warnings(
        seeded,
        batch,  # type: ignore[arg-type]
        user_id="fin.officer",
        note=(
            "Per-deposit accrued profit is still to be confirmed by Absa; the pro-rata "
            "placeholder split is accepted for go-live and will be corrected on receipt."
        ),
    )
    ob.submit(seeded, batch, user_id="fin.officer")  # type: ignore[arg-type]
    result = ob.approve(seeded, batch, approver=approver(seeded))  # type: ignore[arg-type]

    assert result.batch.status is BatchStatus.POSTED
    assert result.holdings_created == 7
    assert len(result.reconciliation.breaks) == 0

    # the ledger now carries the migrated position
    assert balance_of(seeded, "RAYAN", "1220", as_of=CUTOVER) == Decimal("5474000.98")
    assert balance_of(seeded, "RAYAN", "1310", as_of=CUTOVER) == Decimal("16408.80")
    assert balance_of(seeded, "RAYAN", "1140", as_of=CUTOVER) == Decimal("10710.53")
    assert balance_of(seeded, "RAYAN", "2310", as_of=CUTOVER) == Decimal("-10453.08")
    assert balance_of(seeded, "RAYAN", "2110", as_of=CUTOVER) == Decimal("-5000000.00")
    assert balance_of(seeded, "RAYAN", "2210", as_of=CUTOVER) == Decimal("-490667.23")

    statement = reports.client_statement(seeded, "RAYAN", from_date=CUTOVER, to_date=CUTOVER)
    assert statement.your_account.capital_brought_forward == Decimal("5000000.00")
    assert statement.your_account.profit_brought_forward == Decimal("490667.23")
    assert statement.your_account.your_balance == Decimal("5490667.23")
    assert statement.where_held.net_holdings == Decimal("5490667.23")
    assert statement.reconciles
    assert statement.held_reason is None

    # accruals start the day after cutover (this test system does not lock periods)
    for holding in seeded.query(Holding).filter(Holding.client_id == "RAYAN"):
        assert holding.status is HoldingStatus.ACTIVE
        assert holding.accrual_start == date(2026, 2, 1)
        assert holding.opening_accrued > 0
    total_opening = sum(
        holding.opening_accrued
        for holding in seeded.query(Holding).filter(Holding.client_id == "RAYAN")
    )
    assert total_opening == Decimal("16408.80")


@pytest.mark.golden
def test_g1_accrual_continuity_has_no_double_counted_day(seeded: Session) -> None:
    from app.services import accruals
    from app.services import holdings as holdings_svc

    batch = load(seeded, "RAYAN", "rayan", pro_rata=True)
    ob.validate(seeded, batch)  # type: ignore[arg-type]
    ob.acknowledge_warnings(
        seeded,
        batch,
        user_id="fin.officer",
        note="placeholder accepted for go-live",  # type: ignore[arg-type]
    )
    ob.submit(seeded, batch, user_id="fin.officer")  # type: ignore[arg-type]
    ob.approve(seeded, batch, approver=approver(seeded))  # type: ignore[arg-type]

    holding = seeded.get(Holding, "FD-R-03")
    assert holding is not None

    # nothing accrues on the cutover date itself: that day is inside opening accrued
    assert holdings_svc.system_accrued_profit(seeded, holding, CUTOVER) == Decimal("0.00")
    # one day after cutover is one day of profit
    one_day = Decimal("1000000.00") * Decimal("0.0425") / Decimal(365)
    assert holdings_svc.system_accrued_profit(seeded, holding, date(2026, 2, 1)) == Decimal(
        "116.44"
    )
    assert round(one_day, 2) == Decimal("116.44")

    run = accruals.run(seeded, "RAYAN", date(2026, 2, 28), created_by="system")
    assert run.profit_posted > 0
    # 28 days of February on the five full deposits plus the two smaller ones
    assert holdings_svc.profit_to_date(seeded, holding, date(2026, 2, 28)) == Decimal(
        holding.opening_accrued + Decimal("3260.27")
    )


# --- G2 ----------------------------------------------------------------------


@pytest.mark.golden
def test_g2_taaj_opening_batch_is_held_on_suspense(seeded: Session) -> None:
    batch = load(seeded, "TAAJ", "taaj")
    report = ob.validate(seeded, batch)  # type: ignore[arg-type]

    assert report.ok, [f.message for f in report.errors]
    assert report.totals["debits"] == "7614827.62"
    assert report.totals["credits"] == "7614827.62"
    assert report.totals["section_a"] == "7498198.90"
    assert report.totals["section_b"] == "7498198.90"
    assert report.totals["suspense"] == "516745.92"

    codes = {finding.code for finding in report.warnings}
    assert "SUSPENSE_BALANCE" in codes
    assert "PLACEHOLDER_TERMS" in codes

    ob.acknowledge_warnings(
        seeded,
        batch,  # type: ignore[arg-type]
        user_id="fin.officer",
        note=(
            "516,745.92 unreconciled at cutover is under finance review; the per-deposit "
            "breakdown of the Bank of Africa Wakala deposits is awaited."
        ),
    )
    ob.submit(seeded, batch, user_id="fin.officer")  # type: ignore[arg-type]
    ob.approve(seeded, batch, approver=approver(seeded))  # type: ignore[arg-type]

    assert balance_of(seeded, "TAAJ", "1390", as_of=CUTOVER) == Decimal("516745.92")
    assert balance_of(seeded, "TAAJ", "1260", as_of=CUTOVER) == Decimal("2297322.34")
    assert balance_of(seeded, "TAAJ", "1210", as_of=CUTOVER) == Decimal("3286616.33")
    assert balance_of(seeded, "TAAJ", "1320", as_of=CUTOVER) == Decimal("1400509.69")
    assert balance_of(seeded, "TAAJ", "2120", as_of=CUTOVER) == Decimal("-7013618.49")
    assert balance_of(seeded, "TAAJ", "2220", as_of=CUTOVER) == Decimal("-484580.41")

    statement = reports.client_statement(seeded, "TAAJ", from_date=CUTOVER, to_date=CUTOVER)
    assert statement.your_account.your_balance == Decimal("7498198.90")
    assert statement.where_held.net_holdings == Decimal("7498198.90")
    assert statement.reconciles
    assert statement.held_reason is not None
    assert "suspense" in statement.held_reason

    # the placeholder holding does not accrue: its terms are not known
    from app.services import accruals

    run = accruals.run(seeded, "TAAJ", date(2026, 2, 28), created_by="system")
    assert any("FD-T-01" in note for note in run.skipped)
    assert run.profit_posted == Decimal("0.00")


# --- the controls around the batch ------------------------------------------


def test_preparer_can_approve_their_own_batch(seeded: Session) -> None:
    """This test system does not restrict the preparer from approving their
    own batch -- that maker-checker control is deliberately relaxed here."""
    batch = load(seeded, "TAAJ", "taaj")
    ob.validate(seeded, batch)  # type: ignore[arg-type]
    ob.acknowledge_warnings(seeded, batch, user_id="fin.officer", note="ack")  # type: ignore[arg-type]
    ob.submit(seeded, batch, user_id="fin.officer")  # type: ignore[arg-type]
    result = ob.approve(seeded, batch, approver=approver(seeded, "fin.officer"))  # type: ignore[arg-type]
    assert result.batch.status is BatchStatus.POSTED


def test_warnings_must_be_acknowledged_before_submission(seeded: Session) -> None:
    batch = load(seeded, "TAAJ", "taaj")
    ob.validate(seeded, batch)  # type: ignore[arg-type]
    with pytest.raises(BusinessRule):
        ob.submit(seeded, batch, user_id="fin.officer")  # type: ignore[arg-type]


def test_a_second_batch_for_the_same_client_is_allowed(seeded: Session) -> None:
    """This test system deliberately does not restrict a client to one posted
    batch -- see create_batch()'s docstring for why."""
    batch = load(seeded, "TAAJ", "taaj")
    ob.validate(seeded, batch)  # type: ignore[arg-type]
    ob.acknowledge_warnings(seeded, batch, user_id="fin.officer", note="ack")  # type: ignore[arg-type]
    ob.submit(seeded, batch, user_id="fin.officer")  # type: ignore[arg-type]
    ob.approve(seeded, batch, approver=approver(seeded))  # type: ignore[arg-type]
    second = ob.create_batch(
        seeded, client_id="TAAJ", cutover_date=CUTOVER, prepared_by="fin.officer"
    )
    assert second.id != batch.id  # type: ignore[union-attr]
