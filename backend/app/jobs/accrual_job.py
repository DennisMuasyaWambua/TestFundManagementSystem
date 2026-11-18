"""Scheduled jobs: daily accruals and rent, and the month-end revaluation.

Every job here is idempotent (principle 10).  The accrual service computes the
cumulative target for each holding and posts only the difference, and rent invoicing
keys each month's invoice on a unique reference, so a job that runs twice -- or that
is re-run by hand after a failure -- posts nothing the second time.

Each job runs in its own transaction per client, so one client's bad data (a missing
FX rate, say) cannot stop the others from being accrued.  Failures are recorded in
the audit log rather than raised, because a scheduler that dies on the first error
would silently stop accruing for everyone.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select

from app.db import session_scope
from app.enums import SYSTEM_USER
from app.models import Client, RecordStatus
from app.services import accruals, audit, fx

logger = logging.getLogger("fms.jobs")


@dataclass
class JobOutcome:
    """What a job did, per client, so the run can be logged and asserted on."""

    job: str
    as_of: date
    succeeded: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.failed

    def summary(self) -> str:
        return (
            f"{self.job} as at {self.as_of.isoformat()}: "
            f"{len(self.succeeded)} client(s) done, {len(self.failed)} failed"
        )


def active_client_ids() -> list[str]:
    with session_scope() as db:
        return list(
            db.scalars(
                select(Client.id).where(Client.status == RecordStatus.ACTIVE).order_by(Client.id)
            )
        )


def accrue_all(as_of: date | None = None, *, created_by: str = SYSTEM_USER) -> JobOutcome:
    """Daily: accrue profit, invoice rent and charge management fees for every client."""
    as_of = as_of or date.today()
    outcome = JobOutcome(job="DAILY_ACCRUAL", as_of=as_of)

    for client_id in active_client_ids():
        try:
            with session_scope() as db:
                run = accruals.run(db, client_id, as_of, created_by=created_by)
                audit.record(
                    db,
                    user_id=created_by,
                    action="JOB_ACCRUAL",
                    entity="client",
                    entity_id=client_id,
                    client_id=client_id,
                    detail={
                        "as_of": as_of.isoformat(),
                        "profit_posted": f"{run.profit_posted:.2f}",
                        "fee_posted": f"{run.fee_posted:.2f}",
                        "rent_invoices": run.rent_invoices,
                        "skipped": run.skipped,
                    },
                )
            outcome.succeeded.append(client_id)
        except Exception as exc:  # one client's bad data must not stop the rest
            logger.exception("accrual failed for %s", client_id)
            outcome.failed[client_id] = str(exc)
            _record_failure(created_by, "JOB_ACCRUAL_FAILED", client_id, as_of, exc)

    logger.info(outcome.summary())
    return outcome


def revalue_all(as_of: date | None = None, *, created_by: str = SYSTEM_USER) -> JobOutcome:
    """Month-end: restate every foreign-currency balance sheet balance at the closing rate."""
    as_of = as_of or date.today()
    outcome = JobOutcome(job="FX_REVALUATION", as_of=as_of)

    for client_id in active_client_ids():
        try:
            with session_scope() as db:
                result = fx.revalue(db, client_id, as_of, created_by=created_by)
                audit.record(
                    db,
                    user_id=created_by,
                    action="JOB_FX_REVALUATION",
                    entity="client",
                    entity_id=client_id,
                    client_id=client_id,
                    detail={"as_of": as_of.isoformat(), "net": f"{result.net:.2f}"},
                )
            outcome.succeeded.append(client_id)
        except Exception as exc:  # one client's bad data must not stop the rest
            logger.exception("revaluation failed for %s", client_id)
            outcome.failed[client_id] = str(exc)
            _record_failure(created_by, "JOB_FX_REVALUATION_FAILED", client_id, as_of, exc)

    logger.info(outcome.summary())
    return outcome


def _record_failure(
    created_by: str, action: str, client_id: str, as_of: date, exc: Exception
) -> None:
    """Audit a failed job in its own transaction, since the job's own was rolled back."""
    try:
        with session_scope() as db:
            audit.record(
                db,
                user_id=created_by,
                action=action,
                entity="client",
                entity_id=client_id,
                client_id=client_id,
                detail={
                    "as_of": as_of.isoformat(),
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
            )
    except Exception:  # pragma: no cover - the database itself is unreachable
        logger.exception("could not audit the failure of %s for %s", action, client_id)
