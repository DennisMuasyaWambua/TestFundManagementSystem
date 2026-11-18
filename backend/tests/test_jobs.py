"""The scheduled jobs must be idempotent and must not let one client block another.

These are the jobs a CMA-regulated book depends on running unattended overnight, so
the two failure modes that matter are tested directly: a second run that double-posts,
and one client's missing data stopping everybody else's accrual.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from app import db as db_module
from app.jobs import accrual_job
from app.jobs.worker import last_day_of_previous_month, yesterday
from app.models import AuditLog, PeriodLock
from app.services import receipts
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.conftest import add_client, balance_of, run_instruction

CLIENT = "JOBS1"
CUSTODY = f"{CLIENT}-CUST"
DEAL = "FD-JOB-01"
AS_OF = date(2026, 1, 31)


def place_deposit(db: Session, client_id: str, deal_id: str) -> None:
    add_client(db, client_id)
    receipts.record_contribution(
        db,
        client_id=client_id,
        custody_account_id=f"{client_id}-CUST",
        amount=Decimal("1000000.00"),
        value_date=date(2026, 1, 1),
        advice_ref=f"CR-{deal_id}",
        created_by="ops.maker",
    )
    run_instruction(
        db,
        client_id=client_id,
        custody_account_id=f"{client_id}-CUST",
        instruction_type="PLACE_WAKALA",
        amount="1000000.00",
        value_date=date(2026, 1, 1),
        params={
            "holding_id": deal_id,
            "counterparty": "Absa Bank Kenya PLC",
            "profit_rate": "0.0425",
            "day_basis": 365,
            "maturity_date": "2026-08-14",
            "shariah_cert_ref": "SSB/2026/001",
        },
        beneficiary="Absa Bank Kenya PLC - Wakala deposit",
    )


def test_daily_accrual_job_posts_once_and_is_idempotent(seeded: Session) -> None:
    place_deposit(seeded, CLIENT, DEAL)
    seeded.commit()

    first = accrual_job.accrue_all(AS_OF)
    assert first.ok, first.failed
    assert CLIENT in first.succeeded

    # G3's January figure, reached through the job rather than the service.
    with db_module.session_scope() as db:
        assert balance_of(db, CLIENT, "1310") == Decimal("3609.59")
        assert balance_of(db, CLIENT, "4110") == Decimal("-3609.59")

    second = accrual_job.accrue_all(AS_OF)
    assert second.ok, second.failed

    with db_module.session_scope() as db:
        assert balance_of(db, CLIENT, "1310") == Decimal("3609.59")
        assert balance_of(db, CLIENT, "4110") == Decimal("-3609.59")
        posted = db.scalars(
            select(AuditLog)
            .where(AuditLog.action == "JOB_ACCRUAL", AuditLog.client_id == CLIENT)
            .order_by(AuditLog.id)
        ).all()
        # Both runs are audited even though the second posted nothing: an auditor has
        # to be able to see that the job ran, not only that it moved money.
        assert len(posted) == 2
        assert posted[1].detail["profit_posted"] == "0.00"


def test_one_clients_failure_does_not_stop_the_others(seeded: Session) -> None:
    """A client whose period is already closed cannot be accrued; the others still are."""
    place_deposit(seeded, CLIENT, DEAL)
    place_deposit(seeded, "JOBS2", "FD-JOB-02")
    # JOBS2's January is closed, so an accrual entry dated 31 January must be refused.
    seeded.add(PeriodLock(client_id="JOBS2", locked_through=AS_OF, locked_by="fin.head"))
    seeded.commit()

    outcome = accrual_job.accrue_all(AS_OF)

    assert CLIENT in outcome.succeeded
    assert "JOBS2" in outcome.failed
    assert not outcome.ok

    with db_module.session_scope() as db:
        # The healthy client is fully accrued...
        assert balance_of(db, CLIENT, "1310") == Decimal("3609.59")
        # ...the locked one posted nothing at all, not a half-finished entry...
        assert balance_of(db, "JOBS2", "1310") == Decimal("0.00")
        assert balance_of(db, "JOBS2", "4110") == Decimal("0.00")
        # ...and the failure is on the audit trail with its reason.
        failures = db.scalars(select(AuditLog).where(AuditLog.action == "JOB_ACCRUAL_FAILED")).all()
        assert len(failures) == 1
        assert failures[0].client_id == "JOBS2"
        assert "closed through 2026-01-31" in failures[0].detail["error"]
        assert failures[0].detail["error_type"] == "PeriodLocked"


def test_revaluation_job_is_idempotent(seeded: Session) -> None:
    place_deposit(seeded, CLIENT, DEAL)
    seeded.commit()

    first = accrual_job.revalue_all(AS_OF)
    assert first.ok, first.failed
    second = accrual_job.revalue_all(AS_OF)
    assert second.ok, second.failed

    with db_module.session_scope() as db:
        # A USD mandate holding only USD has nothing to revalue, in either run.
        assert balance_of(db, CLIENT, "4210", base=True) == Decimal("0.00")
        assert balance_of(db, CLIENT, "5320", base=True) == Decimal("0.00")


@pytest.mark.parametrize(
    ("today", "expected_accrual_date", "expected_reval_date"),
    [
        (date(2026, 3, 1), date(2026, 2, 28), date(2026, 2, 28)),
        (date(2026, 1, 1), date(2025, 12, 31), date(2025, 12, 31)),
        (date(2026, 8, 15), date(2026, 8, 14), date(2026, 7, 31)),
    ],
)
def test_worker_schedules_look_backwards(
    today: date, expected_accrual_date: date, expected_reval_date: date
) -> None:
    """Profit for day D is only complete once D has ended, so jobs never use today."""
    assert yesterday(today) == expected_accrual_date
    assert last_day_of_previous_month(today) == expected_reval_date
