"""Golden numbers G5 to G9: financing, currencies, Sukuk and property.

G5  Private financing 365,000 at 10%; profit received on day 101 of 10,000; principal
    182,500 repaid the same day; the next 100 days accrue 5,000 on the reduced balance.
G6  KES 10,000,000 Wakala at 10%, 1 Jan to 1 Mar (59 days), KES/USD 0.0080, 0.0078,
    0.0082: capital 80,000 base, January revaluation puts the deposit at 78,000 base
    with a 2,000 exchange loss, maturity profit 161,643.84 KES with 24,246.58 tax and
    10,137,397.26 KES to the bank; after the March close the deposit and accrued base
    balances are zero.
G7  Converting KES 10,000,000 to USD 81,000 at an agreed 0.0081 when the day's rate is
    0.0082 gives an exchange loss of 1,000 and a USD balance of 81,000.
G8  Sukuk nominal 1,000,000 bought at 980,000 at 5% for 2026, valued at 101 on 30 June
    and redeemed at par: fair value adjustment +30,000 then -10,000, net gain 20,000,
    profit on nominal 49,863.01 and 1,069,863.01 in the bank.
G9  Property bought for 2,000,000 and valued at 2,150,000: adjustment 150,000.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from app.models import ApprovalStatus, Holding, HoldingStatus
from app.services import accruals, closing, receipts, reconciliation, reports
from app.services import fx as fx_svc
from app.services import valuation as valuation_svc
from sqlalchemy.orm import Session

from tests.conftest import add_client, add_custody_account, add_fx_rate, balance_of, run_instruction

# --- G5: private financing ---------------------------------------------------

PF_CLIENT = "GOLD5"
PF_CUSTODY = f"{PF_CLIENT}-CUST"
PF_DEAL = "PF-G5-01"


@pytest.mark.golden
def test_g5_part_repayment_reduces_the_accrual(seeded: Session) -> None:
    add_client(seeded, PF_CLIENT, fee_pct="0")
    start = date(2026, 1, 1)
    day_101 = date(2026, 4, 11)
    day_200 = date(2026, 7, 19)
    assert (day_101 - start).days == 100
    assert (day_200 - start).days == 199

    receipts.record_contribution(
        seeded,
        client_id=PF_CLIENT,
        custody_account_id=PF_CUSTODY,
        amount=Decimal("365000.00"),
        value_date=start,
        advice_ref="CR-PF-1",
        created_by="ops.maker",
    )
    run_instruction(
        seeded,
        client_id=PF_CLIENT,
        custody_account_id=PF_CUSTODY,
        instruction_type="DISBURSE_FINANCING",
        amount="365000.00",
        value_date=start,
        params={
            "holding_id": PF_DEAL,
            "counterparty": "<FINANCING COUNTERPARTY>",
            "profit_rate": "0.10",
            "day_basis": 365,
            "maturity_date": "2026-12-31",
            "shariah_cert_ref": "SSB/2026/050",
        },
    )

    # profit for the first 100 days arrives on day 101
    receipts.record_profit(
        seeded,
        holding_id=PF_DEAL,
        gross=Decimal("10000.00"),
        wht=Decimal("0.00"),
        value_date=day_101,
        advice_ref="CR-PF-2",
        created_by="fin.head",
    )
    assert balance_of(seeded, PF_CLIENT, "4120") == Decimal("-10000.00")
    assert balance_of(seeded, PF_CLIENT, "1310") == Decimal("0.00")

    # and half the principal is repaid the same day
    receipts.record_principal(
        seeded,
        holding_id=PF_DEAL,
        amount=Decimal("182500.00"),
        value_date=day_101,
        advice_ref="CR-PF-3",
        created_by="fin.head",
    )
    assert balance_of(seeded, PF_CLIENT, "1250") == Decimal("182500.00")

    # the next 100 days accrue on the reduced balance
    run = accruals.run(seeded, PF_CLIENT, day_200, created_by="system")
    assert run.profit_posted == Decimal("5000.00")
    assert balance_of(seeded, PF_CLIENT, "1310") == Decimal("5000.00")
    assert balance_of(seeded, PF_CLIENT, "4120") == Decimal("-15000.00")


# --- G6: a foreign currency deposit through to a clean close -----------------

FX_CLIENT = "GOLD6"
FX_KES = "GOLD6-KES"
FX_DEAL = "FD-G6-01"


@pytest.mark.golden
def test_g6_foreign_currency_deposit(seeded: Session) -> None:
    add_client(seeded, FX_CLIENT, fee_pct="0")
    add_custody_account(
        seeded,
        FX_CLIENT,
        FX_KES,
        currency="KES",
        cash_code="1160",
        wakala_code="1210",
        custodian="Bank of Africa Kenya",
    )
    add_fx_rate(seeded, "KES", "USD", date(2026, 1, 1), "0.0080")
    add_fx_rate(seeded, "KES", "USD", date(2026, 1, 31), "0.0078")
    add_fx_rate(seeded, "KES", "USD", date(2026, 3, 1), "0.0082")

    receipts.record_contribution(
        seeded,
        client_id=FX_CLIENT,
        custody_account_id=FX_KES,
        amount=Decimal("10000000.00"),
        value_date=date(2026, 1, 1),
        advice_ref="BOA-CR-1",
        created_by="ops.maker",
    )
    assert balance_of(seeded, FX_CLIENT, "2130", base=True) == Decimal("-80000.00")

    run_instruction(
        seeded,
        client_id=FX_CLIENT,
        custody_account_id=FX_KES,
        instruction_type="PLACE_WAKALA",
        amount="10000000.00",
        value_date=date(2026, 1, 1),
        params={
            "holding_id": FX_DEAL,
            "counterparty": "Bank of Africa Kenya",
            "profit_rate": "0.10",
            "day_basis": 365,
            "maturity_date": "2026-03-01",
            "shariah_cert_ref": "SSB/2026/060",
        },
    )

    # January: accrue, then revalue at the closing rate
    accruals.run(seeded, FX_CLIENT, date(2026, 1, 31), created_by="system")
    assert balance_of(seeded, FX_CLIENT, "1310") == Decimal("84931.51")

    reval = fx_svc.revalue(seeded, FX_CLIENT, date(2026, 1, 31), created_by="fin.head")
    assert balance_of(seeded, FX_CLIENT, "1210", base=True) == Decimal("78000.00")
    assert balance_of(seeded, FX_CLIENT, "5320", base=True) == Decimal("2000.00")
    assert reval.net == Decimal("-2000.00")

    # maturity on 1 March
    receipts.record_maturity(
        seeded,
        holding_id=FX_DEAL,
        principal=Decimal("10000000.00"),
        profit=Decimal("161643.84"),
        wht=Decimal("24246.58"),
        value_date=date(2026, 3, 1),
        advice_ref="BOA-CR-9",
        created_by="fin.head",
    )
    assert balance_of(seeded, FX_CLIENT, "1160") == Decimal("10137397.26")
    assert balance_of(seeded, FX_CLIENT, "5210") == Decimal("24246.58")
    assert balance_of(seeded, FX_CLIENT, "4110") == Decimal("-161643.84")

    # March close: the residual base amounts on the cleared balances are realised
    period_end = date(2026, 3, 31)
    reconciliation.record_balance(
        seeded,
        custody_account_id=FX_KES,
        as_of=period_end,
        balance=Decimal("10137397.26"),
        statement_ref="BOA-STMT-2026-03",
        recorded_by="fin.officer",
    )
    reconciliation.record_balance(
        seeded,
        custody_account_id=f"{FX_CLIENT}-CUST",
        as_of=period_end,
        balance=Decimal("0.00"),
        statement_ref="ABSA-STMT-2026-03",
        recorded_by="fin.officer",
    )
    closing.close(seeded, FX_CLIENT, period_end, created_by="fin.head")

    assert balance_of(seeded, FX_CLIENT, "1210", base=True) == Decimal("0.00")
    assert balance_of(seeded, FX_CLIENT, "1210") == Decimal("0.00")
    assert balance_of(seeded, FX_CLIENT, "1310", base=True) == Decimal("0.00")
    assert balance_of(seeded, FX_CLIENT, "1310") == Decimal("0.00")

    statement = reports.client_statement(
        seeded, FX_CLIENT, from_date=date(2026, 1, 1), to_date=period_end
    )
    assert statement.reconciles, statement.held_reason


# --- G7: currency conversion -------------------------------------------------

CONV_CLIENT = "GOLD7"
CONV_KES = "GOLD7-KES"


@pytest.mark.golden
def test_g7_conversion_books_the_rate_difference(seeded: Session) -> None:
    add_client(seeded, CONV_CLIENT, fee_pct="0")
    add_custody_account(
        seeded,
        CONV_CLIENT,
        CONV_KES,
        currency="KES",
        cash_code="1160",
        wakala_code="1210",
        custodian="Bank of Africa Kenya",
    )
    add_fx_rate(seeded, "KES", "USD", date(2026, 1, 1), "0.0082")

    receipts.record_contribution(
        seeded,
        client_id=CONV_CLIENT,
        custody_account_id=CONV_KES,
        amount=Decimal("10000000.00"),
        value_date=date(2026, 1, 1),
        advice_ref="BOA-CR-1",
        created_by="ops.maker",
    )
    run_instruction(
        seeded,
        client_id=CONV_CLIENT,
        custody_account_id=CONV_KES,
        instruction_type="FX_CONVERSION",
        amount="10000000.00",
        value_date=date(2026, 1, 1),
        params={
            "target_custody_account_id": f"{CONV_CLIENT}-CUST",
            "buy_amount": "81000.00",
            "agreed_rate": "0.0081",
        },
        beneficiary="Own USD custody account",
    )

    assert balance_of(seeded, CONV_CLIENT, "1150") == Decimal("81000.00")
    assert balance_of(seeded, CONV_CLIENT, "1160") == Decimal("0.00")
    assert balance_of(seeded, CONV_CLIENT, "5320", base=True) == Decimal("1000.00")
    assert balance_of(seeded, CONV_CLIENT, "1160", base=True) == Decimal("0.00")


# --- G8: Sukuk ---------------------------------------------------------------

SUKUK_CLIENT = "GOLD8"
SUKUK_CUSTODY = f"{SUKUK_CLIENT}-CUST"
SUKUK_DEAL = "SK-G8-01"


@pytest.mark.golden
def test_g8_sukuk_fair_value_and_redemption(seeded: Session) -> None:
    add_client(seeded, SUKUK_CLIENT, fee_pct="0")
    receipts.record_contribution(
        seeded,
        client_id=SUKUK_CLIENT,
        custody_account_id=SUKUK_CUSTODY,
        amount=Decimal("1000000.00"),
        value_date=date(2026, 1, 1),
        advice_ref="CR-SK-1",
        created_by="ops.maker",
    )
    run_instruction(
        seeded,
        client_id=SUKUK_CLIENT,
        custody_account_id=SUKUK_CUSTODY,
        instruction_type="BUY_SUKUK",
        amount="980000.00",
        value_date=date(2026, 1, 1),
        params={
            "holding_id": SUKUK_DEAL,
            "counterparty": "<SUKUK ISSUER>",
            "nominal": "1000000.00",
            "profit_rate": "0.05",
            "day_basis": 365,
            "maturity_date": "2026-12-31",
            "shariah_cert_ref": "SSB/2026/070",
        },
    )
    assert balance_of(seeded, SUKUK_CLIENT, "1230") == Decimal("980000.00")

    # valued at 101 per 100 of nominal on 30 June
    valuation = valuation_svc.propose(
        seeded,
        holding_id=SUKUK_DEAL,
        valuation_date=date(2026, 6, 30),
        source="<EXCHANGE> closing price 30 June 2026",
        prepared_by="ops.maker",
        price=Decimal("101"),
    )
    assert valuation.value == Decimal("1010000.00")
    valuation_svc.approve(seeded, valuation.id, approver_id="fin.head")
    assert seeded.get(type(valuation), valuation.id).status is ApprovalStatus.APPROVED
    assert balance_of(seeded, SUKUK_CLIENT, "1231") == Decimal("30000.00")
    assert balance_of(seeded, SUKUK_CLIENT, "4230") == Decimal("-30000.00")

    accruals.run(seeded, SUKUK_CLIENT, date(2026, 6, 30), created_by="system")

    # redeemed at par on 31 December
    receipts.record_maturity(
        seeded,
        holding_id=SUKUK_DEAL,
        principal=Decimal("1000000.00"),
        profit=Decimal("49863.01"),
        wht=Decimal("0.00"),
        value_date=date(2026, 12, 31),
        advice_ref="CR-SK-9",
        created_by="fin.head",
    )

    assert balance_of(seeded, SUKUK_CLIENT, "5350") == Decimal("10000.00")
    assert balance_of(seeded, SUKUK_CLIENT, "4230") == Decimal("-30000.00")
    net_fair_value_gain = -(
        balance_of(seeded, SUKUK_CLIENT, "4230") + balance_of(seeded, SUKUK_CLIENT, "5350")
    )
    assert net_fair_value_gain == Decimal("20000.00")
    assert balance_of(seeded, SUKUK_CLIENT, "4140") == Decimal("-49863.01")
    assert balance_of(seeded, SUKUK_CLIENT, "1150") == Decimal("1069863.01")
    assert balance_of(seeded, SUKUK_CLIENT, "1230") == Decimal("0.00")
    assert balance_of(seeded, SUKUK_CLIENT, "1231") == Decimal("0.00")
    assert balance_of(seeded, SUKUK_CLIENT, "1310") == Decimal("0.00")
    assert seeded.get(Holding, SUKUK_DEAL).status is HoldingStatus.MATURED


# --- G9: investment property -------------------------------------------------

PROP_CLIENT = "GOLD9"
PROP_CUSTODY = f"{PROP_CLIENT}-CUST"
PROP_DEAL = "PR-G9-01"


@pytest.mark.golden
def test_g9_property_revaluation(seeded: Session) -> None:
    add_client(seeded, PROP_CLIENT, fee_pct="0")
    receipts.record_contribution(
        seeded,
        client_id=PROP_CLIENT,
        custody_account_id=PROP_CUSTODY,
        amount=Decimal("2000000.00"),
        value_date=date(2026, 1, 1),
        advice_ref="CR-PR-1",
        created_by="ops.maker",
    )
    run_instruction(
        seeded,
        client_id=PROP_CLIENT,
        custody_account_id=PROP_CUSTODY,
        instruction_type="PURCHASE_PROPERTY",
        amount="2000000.00",
        value_date=date(2026, 1, 1),
        params={
            "holding_id": PROP_DEAL,
            "counterparty": "<PROPERTY VENDOR>",
            "monthly_rent": "12000.00",
            "shariah_cert_ref": "SSB/2026/080",
        },
    )
    assert balance_of(seeded, PROP_CLIENT, "1260") == Decimal("2000000.00")

    valuation = valuation_svc.propose(
        seeded,
        holding_id=PROP_DEAL,
        valuation_date=date(2026, 6, 30),
        source="Independent valuation report",
        prepared_by="ops.maker",
        value=Decimal("2150000.00"),
        valuer_name="<REGISTERED VALUER>",
        report_ref="VAL/2026/0001",
    )
    valuation_svc.approve(seeded, valuation.id, approver_id="fin.head")

    assert balance_of(seeded, PROP_CLIENT, "1261") == Decimal("150000.00")
    assert balance_of(seeded, PROP_CLIENT, "4230") == Decimal("-150000.00")

    summary = reports.portfolio_summary(seeded, as_of=date(2026, 6, 30))
    property_row = next(
        row
        for row in summary.rows
        if row.client_id == PROP_CLIENT and row.asset_class == "PROPERTY"
    )
    assert property_row.fair_value == Decimal("2150000.00")
