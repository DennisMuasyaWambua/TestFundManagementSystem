"""The ledger itself, plus period locks and FX rates.

``journal_entries`` and ``journal_lines`` are append-only: a database trigger rejects
UPDATE and DELETE on both.  A mistake is corrected by a reversal entry linked through
``reverses_id``, never by editing history.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, MoneyT, RateT
from app.models.base import LedgerEvent, TimestampMixin


class JournalEntry(Base, TimestampMixin):
    __tablename__ = "journal_entries"
    __table_args__ = (
        Index("ix_journal_entries_client_date", "client_id", "entry_date"),
        Index("ix_journal_entries_event", "event"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    event: Mapped[LedgerEvent] = mapped_column(nullable=False)
    client_id: Mapped[str] = mapped_column(String(32), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(120), index=True)
    narrative: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    instruction_id: Mapped[int | None] = mapped_column(Integer, index=True)
    reverses_id: Mapped[int | None] = mapped_column(Integer, index=True)
    batch_id: Mapped[int | None] = mapped_column(Integer, index=True)

    lines: Mapped[list[JournalLine]] = relationship(
        back_populates="entry", lazy="selectin", order_by="JournalLine.id"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<JournalEntry {self.id} {self.entry_date} {self.event}>"


class JournalLine(Base):
    __tablename__ = "journal_lines"
    __table_args__ = (
        Index("ix_journal_lines_client_account", "client_id", "account_code"),
        Index("ix_journal_lines_holding", "holding_id"),
        Index("ix_journal_lines_entry", "entry_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("journal_entries.id"), nullable=False)
    account_code: Mapped[str] = mapped_column(String(10), nullable=False)
    client_id: Mapped[str] = mapped_column(String(32), nullable=False)
    holding_id: Mapped[str | None] = mapped_column(String(48))
    amount: Mapped[Decimal] = mapped_column(MoneyT, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    fx_rate: Mapped[Decimal] = mapped_column(RateT, nullable=False)
    base_amount: Mapped[Decimal] = mapped_column(MoneyT, nullable=False)
    description: Mapped[str] = mapped_column(String(400), nullable=False, default="")

    entry: Mapped[JournalEntry] = relationship(back_populates="lines")

    @property
    def debit(self) -> Decimal:
        return self.amount if self.amount > 0 else Decimal("0.00")

    @property
    def credit(self) -> Decimal:
        return -self.amount if self.amount < 0 else Decimal("0.00")


class PeriodLock(Base, TimestampMixin):
    """Nothing may be posted on or before ``locked_through`` for this client."""

    __tablename__ = "period_locks"

    client_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    locked_through: Mapped[date] = mapped_column(Date, nullable=False)
    locked_by: Mapped[str] = mapped_column(String(64), nullable=False, default="system")


class FxRate(Base, TimestampMixin):
    """Base currency units per one unit of ``currency`` on ``rate_date``."""

    __tablename__ = "fx_rates"
    __table_args__ = (
        UniqueConstraint("currency", "base_currency", "rate_date", name="uq_fx_rate"),
        Index("ix_fx_rates_lookup", "currency", "base_currency", "rate_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    rate_date: Mapped[date] = mapped_column(Date, nullable=False)
    rate: Mapped[Decimal] = mapped_column(RateT, nullable=False)
    source: Mapped[str] = mapped_column(String(120), nullable=False, default="CBK indicative mean")
    entered_by: Mapped[str] = mapped_column(String(64), nullable=False, default="system")
