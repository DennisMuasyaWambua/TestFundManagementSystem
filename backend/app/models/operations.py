"""Valuations, custodian records, reconciliation runs, files and the audit log."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Date, DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, MoneyT, RateT
from app.models.base import ApprovalStatus, FileKind, TimestampMixin, utcnow


class Valuation(Base, TimestampMixin):
    """A proposed fair value for a Sukuk or an investment property, maker-checker."""

    __tablename__ = "valuations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    holding_id: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    client_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    valuation_date: Mapped[date] = mapped_column(Date, nullable=False)
    price: Mapped[Decimal | None] = mapped_column(RateT)
    value: Mapped[Decimal] = mapped_column(MoneyT, nullable=False)
    source: Mapped[str] = mapped_column(String(300), nullable=False)
    valuer_name: Mapped[str | None] = mapped_column(String(200))
    report_ref: Mapped[str | None] = mapped_column(String(120))
    report_file_id: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[ApprovalStatus] = mapped_column(nullable=False, default=ApprovalStatus.PENDING)
    prepared_by: Mapped[str] = mapped_column(String(32), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(32))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    rejection_reason: Mapped[str | None] = mapped_column(String(400))
    journal_entry_id: Mapped[int | None] = mapped_column(Integer)


class ManualJournal(Base, TimestampMixin):
    """A hand-written journal entry, prepared by one finance user and approved by another.

    The proposed lines are held here as data until approval; only then are they posted.
    """

    __tablename__ = "manual_journals"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    narrative: Mapped[str] = mapped_column(String(400), nullable=False)
    lines: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[ApprovalStatus] = mapped_column(nullable=False, default=ApprovalStatus.PENDING)
    prepared_by: Mapped[str] = mapped_column(String(32), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(32))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    rejection_reason: Mapped[str | None] = mapped_column(String(400))
    journal_entry_id: Mapped[int | None] = mapped_column(Integer)


class CustodianBalance(Base, TimestampMixin):
    """A cash balance as the custodian reports it."""

    __tablename__ = "custodian_balances"
    __table_args__ = (UniqueConstraint("custody_account_id", "as_of", name="uq_custodian_balance"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    custody_account_id: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    balance: Mapped[Decimal] = mapped_column(MoneyT, nullable=False)
    statement_ref: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    source_file_id: Mapped[int | None] = mapped_column(Integer)


class CustodianPosition(Base, TimestampMixin):
    """A holding as the custodian reports it."""

    __tablename__ = "custodian_positions"
    __table_args__ = (UniqueConstraint("holding_id", "as_of", name="uq_custodian_position"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    holding_id: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(MoneyT, nullable=False)
    statement_ref: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    source_file_id: Mapped[int | None] = mapped_column(Integer)


class ReconciliationRun(Base, TimestampMixin):
    __tablename__ = "reconciliation_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[str | None] = mapped_column(String(32), index=True)
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default="CASH")
    performed_by: Mapped[str] = mapped_column(String(32), nullable=False)
    performed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    breaks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class StoredFile(Base, TimestampMixin):
    __tablename__ = "files"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kind: Mapped[FileKind] = mapped_column(nullable=False)
    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    content_type: Mapped[str] = mapped_column(
        String(120), nullable=False, default="application/octet-stream"
    )
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(400), nullable=False)
    uploaded_by: Mapped[str] = mapped_column(String(32), nullable=False)


class AuditLog(Base):
    """Append-only: every state change, login, failure, approval and post."""

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_entity", "entity", "entity_id"),
        Index("ix_audit_at", "at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    user_id: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(64))
    client_id: Mapped[str | None] = mapped_column(String(32), index=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64))
