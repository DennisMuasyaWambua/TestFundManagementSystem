"""Golden numbers G3 and G4: a Wakala deposit from placement to a clean close.

G3  USD 1,000,000 at 4.25%, 1 Jan to 14 Aug 2026 (225 days), fee 10%, WHT at source 15%.
    January accrual 3,609.59; total profit 26,198.63; bank at maturity 1,022,268.84;
    fee 2,619.86; tax 3,929.79; client profit after close 19,648.98; after paying the
    profit and the fee: bank 1,000,000.00, capital 1,000,000.00, everything else zero.

G4  The same deposit accrued to 31 March (90 days): income 10,479.45, fee 1,047.95.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from app.ledger import balances
from app.models import AccountType, Holding, HoldingStatus
from app.services import accruals, closing, receipts, reconciliation
from sqlalchemy.orm import Session

from tests.conftest import add_client, balance_of, run_instruction

CLIENT = "GOLD3"
CUSTODY = f"{CLIENT}-CUST"
DEAL = "FD-G3-01"
CASH = "1150"
CAPITAL = "2130"
PROFIT = "2230"
WAKALA = "1220"
ACCRUED = "1310"
WAKALA_INCOME = "4110"
WAKALA_FEE = "5110"
WHT_SOURCE = "5210"
FEE_PAYABLE = "2320"

START = date(2026, 1, 1)
MATURITY = date(2026, 8, 14)


def place_deposit(db: Session) -> None:
    add_client(db, CLIENT)
    receipts.record_contribution(
        db,
        client_id=CLIENT,
        custody_account_id=CUSTODY,
        amount=Decimal("1000000.00"),
        value_date=START,
        advice_ref="ABSA-CR-0001",
        created_by="ops.maker",
    )
    run_instruction(
        db,
        client_id=CLIENT,
        custody_account_id=CUSTODY,
        instruction_type="PLACE_WAKALA",
        amount="1000000.00",
        value_date=START,
        params={
            "holding_id": DEAL,
            "counterparty": "Absa Bank Kenya PLC",
            "profit_rate": "0.0425",
            "day_basis": 365,
            "maturity_date": MATURITY.isoformat(),
            "shariah_cert_ref": "SSB/2026/001",
            "external_ref": "ABSA-FD-991",
        },
        beneficiary="Absa Bank Kenya PLC - Wakala deposit",
    )


@pytest.mark.golden
def test_g3_january_accrual(seeded: Session) -> None:
    place_deposit(seeded)
    run = accruals.run(seeded, CLIENT, date(2026, 1, 31), created_by="system")
    assert run.profit_posted == Decimal("3609.59")
    assert balance_of(seeded, CLIENT, ACCRUED) == Decimal("3609.59")
    assert balance_of(seeded, CLIENT, WAKALA_INCOME) == Decimal("-3609.59")
    assert balance_of(seeded, CLIENT, WAKALA_FEE) == Decimal("360.96")


@pytest.mark.golden
def test_g4_three_month_accrual_and_fee(seeded: Session) -> None:
    place_deposit(seeded)
    accruals.run(seeded, CLIENT, date(2026, 1, 31), created_by="system")
    accruals.run(seeded, CLIENT, date(2026, 2, 28), created_by="system")
    accruals.run(seeded, CLIENT, date(2026, 3, 31), created_by="system")

    assert balance_of(seeded, CLIENT, WAKALA_INCOME) == Decimal("-10479.45")
    assert balance_of(seeded, CLIENT, WAKALA_FEE) == Decimal("1047.95")
    assert balance_of(seeded, CLIENT, FEE_PAYABLE) == Decimal("-1047.95")


@pytest.mark.golden
def test_accrual_runs_are_idempotent(seeded: Session) -> None:
    place_deposit(seeded)
    first = accruals.run(seeded, CLIENT, date(2026, 3, 31), created_by="system")
    assert first.changed
    again = accruals.run(seeded, CLIENT, date(2026, 3, 31), created_by="system")
    assert not again.changed
    assert again.profit_posted == Decimal("0.00")
    assert again.fee_posted == Decimal("0.00")
    assert balance_of(seeded, CLIENT, WAKALA_INCOME) == Decimal("-10479.45")


@pytest.mark.golden
def test_g3_full_cycle_to_zero(seeded: Session) -> None:
    place_deposit(seeded)

    # accrue through the life of the deposit, monthly
    for as_of in (
        date(2026, 1, 31),
        date(2026, 2, 28),
        date(2026, 3, 31),
        date(2026, 4, 30),
        date(2026, 5, 31),
        date(2026, 6, 30),
        date(2026, 7, 31),
    ):
        accruals.run(seeded, CLIENT, as_of, created_by="system")

    # maturity: principal plus 225 days of profit, less 15% tax at source
    receipts.record_maturity(
        seeded,
        holding_id=DEAL,
        principal=Decimal("1000000.00"),
        profit=Decimal("26198.63"),
        wht=Decimal("3929.79"),
        value_date=MATURITY,
        advice_ref="ABSA-CR-0042",
        created_by="fin.head",
    )

    assert balance_of(seeded, CLIENT, WAKALA_INCOME) == Decimal("-26198.63")
    assert balance_of(seeded, CLIENT, CASH) == Decimal("1022268.84")
    assert balance_of(seeded, CLIENT, WAKALA_FEE) == Decimal("2619.86")
    assert balance_of(seeded, CLIENT, WHT_SOURCE) == Decimal("3929.79")
    assert balance_of(seeded, CLIENT, WAKALA) == Decimal("0.00")
    assert balance_of(seeded, CLIENT, ACCRUED) == Decimal("0.00")

    holding = seeded.get(Holding, DEAL)
    assert holding is not None
    assert holding.status is HoldingStatus.MATURED

    # month-end close moves the result to the client
    period_end = date(2026, 8, 31)
    reconciliation.record_balance(
        seeded,
        custody_account_id=CUSTODY,
        as_of=period_end,
        balance=Decimal("1022268.84"),
        statement_ref="ABSA-STMT-2026-08",
        recorded_by="fin.officer",
    )
    result = closing.close(seeded, CLIENT, period_end, created_by="fin.head")
    assert result.net_profit == Decimal("19648.98")
    assert balance_of(seeded, CLIENT, PROFIT) == Decimal("-19648.98")
    for code in (WAKALA_INCOME, WAKALA_FEE, WHT_SOURCE):
        assert balance_of(seeded, CLIENT, code) == Decimal("0.00"), code

    # pay the client its profit and the bank its fee
    pay_day = date(2026, 9, 1)
    run_instruction(
        seeded,
        client_id=CLIENT,
        custody_account_id=CUSTODY,
        instruction_type="PAY_CLIENT_PROFIT",
        amount="19648.98",
        value_date=pay_day,
        client_instruction_ref="CLIENT-REQ-2026-09-01",
        beneficiary=f"{CLIENT} Test Mandate",
        confirmation_ref="ABSA-DR-0101",
    )
    run_instruction(
        seeded,
        client_id=CLIENT,
        custody_account_id=CUSTODY,
        instruction_type="PAY_MGMT_FEE",
        amount="2619.86",
        value_date=pay_day,
        beneficiary="SIBK Capital Limited",
        confirmation_ref="ABSA-DR-0102",
    )

    assert balance_of(seeded, CLIENT, CASH) == Decimal("1000000.00")
    assert balance_of(seeded, CLIENT, CAPITAL) == Decimal("-1000000.00")
    for code in (
        WAKALA,
        ACCRUED,
        WAKALA_INCOME,
        WAKALA_FEE,
        WHT_SOURCE,
        FEE_PAYABLE,
        PROFIT,
    ):
        assert balance_of(seeded, CLIENT, code) == Decimal("0.00"), code

    rows = balances.trial_balance(seeded, as_of=date(2026, 12, 31), client_id=CLIENT)
    assert sum((row.base_amount for row in rows), Decimal(0)) == Decimal("0.00")
    assert {row.account_code for row in rows if row.type is AccountType.ASSET} == {CASH}
