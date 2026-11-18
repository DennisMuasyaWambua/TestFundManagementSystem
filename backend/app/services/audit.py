"""The audit trail.

Every state change, login, failure, approval and post writes a row here.  The table is
append-only at the database level, so an audit row cannot be edited or removed once
written -- which is what CoB regs 32-35 and the 7-year retention rule require.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog, utcnow


def record(
    db: Session,
    *,
    user_id: str,
    action: str,
    entity: str,
    entity_id: str | int | None = None,
    client_id: str | None = None,
    detail: dict[str, Any] | None = None,
    ip: str | None = None,
) -> AuditLog:
    row = AuditLog(
        at=utcnow(),
        user_id=user_id,
        action=action,
        entity=entity,
        entity_id=None if entity_id is None else str(entity_id),
        client_id=client_id,
        detail=detail or {},
        ip=ip,
    )
    db.add(row)
    db.flush()
    return row
