"""Property-based tests for the ledger invariants.

For *any* sequence of valid events: every entry balances in its own currency and in
base currency, the trial balance balances, every client statement has A = B, and no
client's line ever lands on another client's owned account.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.ledger import balances
from app.models import AccountType, JournalEntry, LedgerEvent
from app.money import money
from app.services import accruals, closing, receipts, reconciliation, reports
from app.services import fx as fx_svc
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy.orm import Session

from tests.conftest import add_client, fresh_session, run_instruction

CLIENT = "PROP"
CUSTODY = f"{CLIENT}-CUST"
START = date(2026, 1, 1)

amounts = st.integers(min_value=1_000, max_value=5_000_000).map(lambda cents: Decimal(cents) / 100)
rates = st.sampled_from(["0.02", "0.0325", "0.0425", "0.05", "0.10"]).map(Decimal)
day_offsets = st.integers(min_value=1, max_value=300)


def assert_every_entry_balances(db: Session) -> None:
    for entry in db.query(JournalEntry).all():
        per_currency: dict[str, Decimal] = {}
        base_total = Decimal(0)
        for line in entry.lines:
            per_currency[line.currency] = per_currency.get(line.currency, Decimal(0)) + line.amount
            base_total += line.base_amount
        assert money(base_total) == Decimal("0.00"), (
            f"entry {entry.id} ({entry.event}) does not balance in base: {base_total}"
        )
        if len(per_currency) == 1 and entry.event not in (
            LedgerEvent.FX_REVALUATION,
            LedgerEvent.FX_CONVERSION,
        ):
            only = next(iter(per_currency.values()))
            assert money(only) == Decimal("0.00"), (
                f"entry {entry.id} ({entry.event}) does not balance in its own currency: {only}"
            )
        assert len(entry.lines) >= 2


def assert_trial_balance_balances(db: Session, as_of: date) -> None:
    rows = balances.trial_balance(db, as_of=as_of)
    assert money(sum((row.base_amount for row in rows), Decimal(0))) == Decimal("0.00")


def assert_statement_reconciles(db: Session, client_id: str, as_of: date) -> None:
    statement = reports.client_statement(db, client_id, from_date=date(1900, 1, 1), to_date=as_of)
    assert statement.your_account.your_balance == statement.where_held.net_holdings, (
        f"A ({statement.your_account.your_balance}) != B "
        f"({statement.where_held.net_holdings}) for {client_id} at {as_of}"
    )


def assert_no_cross_client_lines(db: Session) -> None:
    from app.ledger.roles import client_owned_accounts
    from app.models import JournalLine

    owners = client_owned_accounts(db)
    for line in db.query(JournalLine).all():
        owner = owners.get(line.account_code)
        assert owner is None or owner == line.client_id
    for entry in db.query(JournalEntry).all():
        assert {line.client_id for line in entry.lines} == {entry.client_id}
    equity_codes = [
        row.account_code
        for row in balances.by_account(db, client_id=None, types=(AccountType.EQUITY,))
    ]
    assert equity_codes == [], "equity accounts must never hold client money"


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    contribution=amounts,
    placement=st.integers(min_value=10, max_value=90),
    rate=rates,
    term=day_offsets,
    accrue_after=day_offsets,
)
def test_invariants_hold_for_any_wakala_lifecycle(
    contribution: Decimal,
    placement: int,
    rate: Decimal,
    term: int,
    accrue_after: int,
) -> None:
    with fresh_session() as seeded:
        _wakala_lifecycle(seeded, contribution, placement, rate, term, accrue_after)


def _wakala_lifecycle(
    seeded: Session,
    contribution: Decimal,
    placement: int,
    rate: Decimal,
    term: int,
    accrue_after: int,
) -> None:
    add_client(seeded, CLIENT)
    deal = "FD-PROP-01"
    maturity = START + timedelta(days=term)
    placed = money(contribution * Decimal(placement) / 100)
    if placed <= 0:
        return

    receipts.record_contribution(
        seeded,
        client_id=CLIENT,
        custody_account_id=CUSTODY,
        amount=contribution,
        value_date=START,
        advice_ref="CR-PROP",
        created_by="ops.maker",
    )
    run_instruction(
        seeded,
        client_id=CLIENT,
        custody_account_id=CUSTODY,
        instruction_type="PLACE_WAKALA",
        amount=f"{placed:.2f}",
        value_date=START,
        params={
            "holding_id": deal,
            "counterparty": "Absa Bank Kenya PLC",
            "profit_rate": f"{rate:f}",
            "day_basis": 365,
            "maturity_date": maturity.isoformat(),
            "shariah_cert_ref": "SSB/PROP",
        },
    )

    as_of = START + timedelta(days=accrue_after)
    accruals.run(seeded, CLIENT, as_of, created_by="system")

    assert_every_entry_balances(seeded)
    assert_trial_balance_balances(seeded, as_of)
    assert_statement_reconciles(seeded, CLIENT, as_of)
    assert_no_cross_client_lines(seeded)

    # re-running the accrual changes nothing
    again = accruals.run(seeded, CLIENT, as_of, created_by="system")
    assert not again.changed
    assert_statement_reconciles(seeded, CLIENT, as_of)


@settings(max_examples=15, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(amount=amounts, rate=rates)
def test_invariants_hold_through_a_month_end_close(amount: Decimal, rate: Decimal) -> None:
    with fresh_session() as seeded:
        _month_end_close(seeded, amount, rate)


def _month_end_close(seeded: Session, amount: Decimal, rate: Decimal) -> None:
    add_client(seeded, CLIENT)
    deal = "FD-PROP-CLOSE"
    receipts.record_contribution(
        seeded,
        client_id=CLIENT,
        custody_account_id=CUSTODY,
        amount=amount,
        value_date=START,
        advice_ref="CR-PROP",
        created_by="ops.maker",
    )
    run_instruction(
        seeded,
        client_id=CLIENT,
        custody_account_id=CUSTODY,
        instruction_type="PLACE_WAKALA",
        amount=f"{amount:.2f}",
        value_date=START,
        params={
            "holding_id": deal,
            "counterparty": "Absa Bank Kenya PLC",
            "profit_rate": f"{rate:f}",
            "day_basis": 365,
            "maturity_date": "2026-12-31",
            "shariah_cert_ref": "SSB/PROP",
        },
    )
    period_end = date(2026, 1, 31)
    reconciliation.record_balance(
        seeded,
        custody_account_id=CUSTODY,
        as_of=period_end,
        balance=Decimal("0.00"),
        statement_ref="STMT",
        recorded_by="fin.officer",
    )
    reconciliation.record_position(
        seeded,
        holding_id=deal,
        as_of=period_end,
        amount=amount,
        statement_ref="STMT",
        recorded_by="fin.officer",
    )

    first = closing.close(seeded, CLIENT, period_end, created_by="fin.head")
    assert not first.already_closed
    assert_every_entry_balances(seeded)
    assert_trial_balance_balances(seeded, period_end)
    assert_statement_reconciles(seeded, CLIENT, period_end)

    # closing the same period again is a no-op
    second = closing.close(seeded, CLIENT, period_end, created_by="fin.head")
    assert second.already_closed
    assert second.net_profit == Decimal("0.00")

    # and so is re-running the revaluation
    reval = fx_svc.revalue(
        seeded, CLIENT, period_end, created_by="fin.head", bypass_period_lock=True
    )
    assert not reval.changed
