"""Ledger invariants: balance, segregation, immutability, locks and roles."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from app.errors import (
    AccountNotPostable,
    HoldingRequired,
    MissingFxRate,
    PeriodLocked,
    SegregationBreach,
    UnbalancedEntry,
)
from app.ledger import balances
from app.ledger.posting import LineDraft, post
from app.ledger.reversal import reverse_entry
from app.ledger.roles import Role, resolve
from app.models import JournalEntry, LedgerEvent, PeriodLock
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session

from tests.conftest import add_client, add_fx_rate

JAN = date(2026, 1, 15)


def contribution(client_id: str = "ACME", amount: str = "1000.00") -> list[LineDraft]:
    return [
        LineDraft(account_code="1150", amount=Decimal(amount), client_id=client_id),
        LineDraft(account_code="2130", amount=-Decimal(amount), client_id=client_id),
    ]


def test_post_writes_entry_and_lines(seeded: Session) -> None:
    add_client(seeded, "ACME")
    entry = post(
        seeded,
        entry_date=JAN,
        event=LedgerEvent.CLIENT_CONTRIBUTION,
        client_id="ACME",
        currency="USD",
        lines=contribution(),
        narrative="Opening contribution",
        created_by="test",
    )
    assert entry.id is not None
    assert len(entry.lines) == 2
    assert all(line.base_amount == line.amount for line in entry.lines)
    assert balances.balance(seeded, client_id="ACME", account_code="1150") == Decimal("1000.00")
    assert balances.balance(seeded, client_id="ACME", account_code="2130") == Decimal("-1000.00")


def test_unbalanced_entry_is_rejected(seeded: Session) -> None:
    add_client(seeded, "ACME")
    lines = [
        LineDraft(account_code="1150", amount=Decimal("1000.00"), client_id="ACME"),
        LineDraft(account_code="2130", amount=Decimal("-999.00"), client_id="ACME"),
    ]
    with pytest.raises(UnbalancedEntry):
        post(
            seeded,
            entry_date=JAN,
            event=LedgerEvent.CLIENT_CONTRIBUTION,
            client_id="ACME",
            currency="USD",
            lines=lines,
            created_by="test",
        )


def test_single_line_entry_is_rejected(seeded: Session) -> None:
    add_client(seeded, "ACME")
    with pytest.raises(UnbalancedEntry):
        post(
            seeded,
            entry_date=JAN,
            event=LedgerEvent.MANUAL,
            client_id="ACME",
            currency="USD",
            lines=[LineDraft(account_code="1150", amount=Decimal("0.00"), client_id="ACME")],
            created_by="test",
        )


def test_heading_account_is_not_postable(seeded: Session) -> None:
    add_client(seeded, "ACME")
    lines = [
        LineDraft(account_code="1100", amount=Decimal("10.00"), client_id="ACME"),
        LineDraft(account_code="2130", amount=Decimal("-10.00"), client_id="ACME"),
    ]
    with pytest.raises(AccountNotPostable):
        post(
            seeded,
            entry_date=JAN,
            event=LedgerEvent.MANUAL,
            client_id="ACME",
            currency="USD",
            lines=lines,
            created_by="test",
        )


def test_sub_ledger_account_needs_a_holding(seeded: Session) -> None:
    add_client(seeded, "ACME")
    lines = [
        LineDraft(account_code="1220", amount=Decimal("10.00"), client_id="ACME"),
        LineDraft(account_code="1150", amount=Decimal("-10.00"), client_id="ACME"),
    ]
    with pytest.raises(HoldingRequired):
        post(
            seeded,
            entry_date=JAN,
            event=LedgerEvent.INVESTMENT_PLACED,
            client_id="ACME",
            currency="USD",
            lines=lines,
            created_by="test",
        )


def test_another_clients_owned_account_is_rejected(seeded: Session) -> None:
    # 2110 is Rayan's capital account and 1140 is Rayan's USD custody cash;
    # neither may take a line for Taaj.
    for lines in (
        [
            LineDraft(account_code="1120", amount=Decimal("10.00"), client_id="TAAJ"),
            LineDraft(account_code="2110", amount=Decimal("-10.00"), client_id="TAAJ"),
        ],
        [
            LineDraft(account_code="1140", amount=Decimal("10.00"), client_id="TAAJ"),
            LineDraft(account_code="2120", amount=Decimal("-10.00"), client_id="TAAJ"),
        ],
    ):
        with pytest.raises(SegregationBreach):
            post(
                seeded,
                entry_date=JAN,
                event=LedgerEvent.CLIENT_CONTRIBUTION,
                client_id="TAAJ",
                currency="USD",
                lines=lines,
                created_by="test",
            )


def test_line_for_a_different_client_is_rejected(seeded: Session) -> None:
    add_client(seeded, "ACME")
    add_client(
        seeded,
        "OTHER",
        capital_code="2120",
        profit_code="2220",
        custody=("BOA", "USD", "1120", "1210", "Bank of Africa Kenya"),
    )
    lines = [
        LineDraft(account_code="1320", amount=Decimal("10.00"), client_id="ACME"),
        LineDraft(account_code="2310", amount=Decimal("-10.00"), client_id="OTHER"),
    ]
    with pytest.raises(SegregationBreach):
        post(
            seeded,
            entry_date=JAN,
            event=LedgerEvent.MANUAL,
            client_id="ACME",
            currency="USD",
            lines=lines,
            created_by="test",
        )


def test_equity_accounts_cannot_hold_client_money(seeded: Session) -> None:
    add_client(seeded, "ACME")
    lines = [
        LineDraft(account_code="1150", amount=Decimal("10.00"), client_id="ACME"),
        LineDraft(account_code="3110", amount=Decimal("-10.00"), client_id="ACME"),
    ]
    with pytest.raises(SegregationBreach):
        post(
            seeded,
            entry_date=JAN,
            event=LedgerEvent.MANUAL,
            client_id="ACME",
            currency="USD",
            lines=lines,
            created_by="test",
        )


def test_posting_into_a_closed_period_is_rejected(seeded: Session) -> None:
    add_client(seeded, "ACME")
    seeded.add(PeriodLock(client_id="ACME", locked_through=date(2026, 1, 31), locked_by="test"))
    seeded.flush()
    with pytest.raises(PeriodLocked):
        post(
            seeded,
            entry_date=date(2026, 1, 31),
            event=LedgerEvent.CLIENT_CONTRIBUTION,
            client_id="ACME",
            currency="USD",
            lines=contribution(),
            created_by="test",
        )
    # the day after the lock is fine
    post(
        seeded,
        entry_date=date(2026, 2, 1),
        event=LedgerEvent.CLIENT_CONTRIBUTION,
        client_id="ACME",
        currency="USD",
        lines=contribution(),
        created_by="test",
    )


def test_missing_fx_rate_is_a_hard_error(seeded: Session) -> None:
    add_client(seeded, "ACME")
    lines = [
        LineDraft(account_code="1160", amount=Decimal("1000.00"), client_id="ACME"),
        LineDraft(account_code="2130", amount=Decimal("-1000.00"), client_id="ACME"),
    ]
    with pytest.raises(MissingFxRate) as excinfo:
        post(
            seeded,
            entry_date=JAN,
            event=LedgerEvent.CLIENT_CONTRIBUTION,
            client_id="ACME",
            currency="KES",
            lines=lines,
            created_by="test",
        )
    assert "KES" in str(excinfo.value)


def test_foreign_currency_entry_carries_base_amounts(seeded: Session) -> None:
    add_client(seeded, "ACME")
    add_fx_rate(seeded, "KES", "USD", date(2026, 1, 1), "0.0080")
    lines = [
        LineDraft(account_code="1160", amount=Decimal("1000000.00"), client_id="ACME"),
        LineDraft(account_code="2130", amount=Decimal("-1000000.00"), client_id="ACME"),
    ]
    entry = post(
        seeded,
        entry_date=JAN,
        event=LedgerEvent.CLIENT_CONTRIBUTION,
        client_id="ACME",
        currency="KES",
        lines=lines,
        created_by="test",
    )
    assert {line.base_amount for line in entry.lines} == {
        Decimal("8000.00"),
        Decimal("-8000.00"),
    }
    assert balances.balance(seeded, client_id="ACME", account_code="1160", base=True) == Decimal(
        "8000.00"
    )


def test_journal_entries_are_append_only(seeded: Session) -> None:
    add_client(seeded, "ACME")
    entry = post(
        seeded,
        entry_date=JAN,
        event=LedgerEvent.CLIENT_CONTRIBUTION,
        client_id="ACME",
        currency="USD",
        lines=contribution(),
        created_by="test",
    )
    seeded.commit()
    for statement in (
        f"UPDATE journal_entries SET narrative = 'tampered' WHERE id = {entry.id}",
        f"DELETE FROM journal_entries WHERE id = {entry.id}",
        f"UPDATE journal_lines SET amount = 1 WHERE entry_id = {entry.id}",
        f"DELETE FROM journal_lines WHERE entry_id = {entry.id}",
        "UPDATE audit_log SET action = 'tampered'",
        "DELETE FROM audit_log",
    ):
        with pytest.raises(DatabaseError):
            seeded.execute(text(statement))
        seeded.rollback()


def test_reversal_mirrors_the_original(seeded: Session) -> None:
    add_client(seeded, "ACME")
    original = post(
        seeded,
        entry_date=JAN,
        event=LedgerEvent.CLIENT_CONTRIBUTION,
        client_id="ACME",
        currency="USD",
        lines=contribution(),
        created_by="test",
    )
    reversal = reverse_entry(
        seeded, original.id, reason="keyed against the wrong mandate", created_by="fin.head"
    )
    assert reversal.reverses_id == original.id
    assert reversal.event is LedgerEvent.REVERSAL
    assert balances.balance(seeded, client_id="ACME", account_code="1150") == Decimal("0.00")
    # a second reversal of the same entry is refused
    from app.errors import Conflict

    with pytest.raises(Conflict):
        reverse_entry(seeded, original.id, reason="again", created_by="fin.head")


def test_roles_resolve_per_client(seeded: Session) -> None:
    assert resolve(seeded, "RAYAN", Role.CLIENT_CAPITAL) == "2110"
    assert resolve(seeded, "TAAJ", Role.CLIENT_CAPITAL) == "2120"
    assert resolve(seeded, "RAYAN", Role.ACCRUED_INCOME) == "1310"
    assert resolve(seeded, "TAAJ", Role.ACCRUED_INCOME) == "1310"


def test_trial_balance_balances(seeded: Session) -> None:
    add_client(seeded, "ACME")
    post(
        seeded,
        entry_date=JAN,
        event=LedgerEvent.CLIENT_CONTRIBUTION,
        client_id="ACME",
        currency="USD",
        lines=contribution(amount="12345.67"),
        created_by="test",
    )
    rows = balances.trial_balance(seeded, as_of=date(2026, 12, 31))
    assert sum((row.base_amount for row in rows), Decimal(0)) == Decimal("0.00")


def test_every_posted_entry_is_linked_to_an_audit_row(seeded: Session) -> None:
    from app.models import AuditLog

    add_client(seeded, "ACME")
    post(
        seeded,
        entry_date=JAN,
        event=LedgerEvent.CLIENT_CONTRIBUTION,
        client_id="ACME",
        currency="USD",
        lines=contribution(),
        created_by="ops.maker",
    )
    entries = seeded.query(JournalEntry).count()
    posts = seeded.query(AuditLog).filter(AuditLog.action == "LEDGER_POST").count()
    assert entries == posts == 1
