"""Opening balance migration: the batch and its staging rows.

Nothing in these tables touches the ledger until the batch reaches POSTED, and a
posted batch can only be undone by a reversal batch approved the same way.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, MoneyT, RateT
from app.models.base import AssetClass, BatchStatus, ProfitTreatment, TimestampMixin


class OpeningBalanceBatch(Base, TimestampMixin):
    __tablename__ = "opening_balance_batches"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    cutover_date: Mapped[date] = mapped_column(Date, nullable=False)
    profit_treatment: Mapped[ProfitTreatment] = mapped_column(
        nullable=False, default=ProfitTreatment.CLIENT_PROFIT_ONLY
    )
    status: Mapped[BatchStatus] = mapped_column(
        nullable=False, default=BatchStatus.DRAFT, index=True
    )
    pro_rata_accrual_split: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_files: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    validation_report: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    warnings_acknowledged_by: Mapped[str | None] = mapped_column(String(32))
    warnings_acknowledged_note: Mapped[str | None] = mapped_column(String(600))
    prepared_by: Mapped[str] = mapped_column(String(32), nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    approved_by: Mapped[str | None] = mapped_column(String(32))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    rejection_reason: Mapped[str | None] = mapped_column(String(600))
    journal_entry_id: Mapped[int | None] = mapped_column(Integer)
    reverses_batch_id: Mapped[int | None] = mapped_column(Integer)

    holdings: Mapped[list[OpeningBalanceHolding]] = relationship(
        back_populates="batch",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="OpeningBalanceHolding.row_number",
    )
    lines: Mapped[list[OpeningBalanceLine]] = relationship(
        back_populates="batch",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="OpeningBalanceLine.row_number",
    )

    @property
    def include_pl(self) -> bool:
        return self.profit_treatment is ProfitTreatment.INCLUDE_PL


class OpeningBalanceHolding(Base, TimestampMixin):
    __tablename__ = "opening_balance_holdings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("opening_balance_batches.id"), nullable=False, index=True
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    holding_id: Mapped[str] = mapped_column(String(48), nullable=False)
    asset_class: Mapped[AssetClass] = mapped_column(nullable=False)
    custody_account: Mapped[str] = mapped_column(String(64), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    counterparty: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    face_amount: Mapped[Decimal] = mapped_column(MoneyT, nullable=False)
    nominal: Mapped[Decimal | None] = mapped_column(MoneyT)
    profit_rate: Mapped[Decimal | None] = mapped_column(RateT)
    day_basis: Mapped[int] = mapped_column(Integer, nullable=False, default=365)
    start_date: Mapped[date | None] = mapped_column(Date)
    maturity_date: Mapped[date | None] = mapped_column(Date)
    monthly_rent: Mapped[Decimal | None] = mapped_column(MoneyT)
    shariah_cert_ref: Mapped[str | None] = mapped_column(String(120))
    external_ref: Mapped[str | None] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    is_placeholder: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    batch: Mapped[OpeningBalanceBatch] = relationship(back_populates="holdings")


class OpeningBalanceLine(Base, TimestampMixin):
    __tablename__ = "opening_balance_lines"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("opening_balance_batches.id"), nullable=False, index=True
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    account_code: Mapped[str] = mapped_column(String(10), nullable=False)
    holding_id: Mapped[str | None] = mapped_column(String(48))
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    debit: Mapped[Decimal] = mapped_column(MoneyT, nullable=False, default=Decimal("0"))
    credit: Mapped[Decimal] = mapped_column(MoneyT, nullable=False, default=Decimal("0"))
    description: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    derived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    batch: Mapped[OpeningBalanceBatch] = relationship(back_populates="lines")

    @property
    def signed(self) -> Decimal:
        """Debit positive, credit negative -- the ledger convention."""
        return self.debit - self.credit


class OpeningCustodianRow(Base, TimestampMixin):
    """Staged custodian statement figures, used for the post-load reconciliation."""

    __tablename__ = "opening_balance_custodian_rows"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("opening_balance_batches.id"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(MoneyT, nullable=False)
    statement_ref: Mapped[str] = mapped_column(String(120), nullable=False, default="")
