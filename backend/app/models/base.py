"""Column mixins shared by every table."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.enums import (
    INVESTMENT_INSTRUCTIONS,
    NORMAL_BALANCE_BY_TYPE,
    PIPELINE_STATUSES,
    REPORT_BY_TYPE,
    SYSTEM_USER,
    AccountType,
    ApprovalStatus,
    AssetClass,
    BatchStatus,
    FileKind,
    HoldingStatus,
    InstructionStatus,
    InstructionType,
    KycStatus,
    LedgerEvent,
    NormalBalance,
    ProfitTreatment,
    RecordStatus,
    ReportSection,
    RiskRating,
    UserRole,
)

__all__ = [
    "INVESTMENT_INSTRUCTIONS",
    "NORMAL_BALANCE_BY_TYPE",
    "PIPELINE_STATUSES",
    "REPORT_BY_TYPE",
    "SYSTEM_USER",
    "AccountType",
    "ApprovalStatus",
    "AssetClass",
    "BatchStatus",
    "FileKind",
    "HoldingStatus",
    "InstructionStatus",
    "InstructionType",
    "KycStatus",
    "LedgerEvent",
    "MutableMixin",
    "NormalBalance",
    "ProfitTreatment",
    "RecordStatus",
    "ReportSection",
    "RiskRating",
    "TimestampMixin",
    "UserRole",
    "utcnow",
]


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(String(64), nullable=False, default=SYSTEM_USER)


class MutableMixin(TimestampMixin):
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(64))
