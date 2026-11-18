"""Holdings: one row per investment the bank manages for a client.

A holding carries its *terms* only.  Its balances -- outstanding principal, accrued
profit, fair value adjustment -- are never stored here; they are always derived from
the ledger, so there is exactly one version of the truth.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, MoneyT, RateT
from app.models.base import AssetClass, HoldingStatus, MutableMixin


class Holding(Base, MutableMixin):
    __tablename__ = "holdings"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    client_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    asset_class: Mapped[AssetClass] = mapped_column(nullable=False, index=True)
    custody_account_id: Mapped[str] = mapped_column(String(48), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    counterparty: Mapped[str] = mapped_column(String(200), nullable=False)
    related_party: Mapped[bool] = mapped_column(nullable=False, default=False)
    description: Mapped[str] = mapped_column(String(400), nullable=False, default="")

    face_amount: Mapped[Decimal] = mapped_column(MoneyT, nullable=False)
    nominal: Mapped[Decimal | None] = mapped_column(MoneyT)
    profit_rate: Mapped[Decimal | None] = mapped_column(RateT)
    day_basis: Mapped[int] = mapped_column(Integer, nullable=False, default=365)
    start_date: Mapped[date | None] = mapped_column(Date)
    maturity_date: Mapped[date | None] = mapped_column(Date)
    monthly_rent: Mapped[Decimal | None] = mapped_column(MoneyT)

    accrual_start: Mapped[date | None] = mapped_column(Date)
    opening_accrued: Mapped[Decimal] = mapped_column(MoneyT, nullable=False, default=Decimal("0"))
    opening_batch_id: Mapped[int | None] = mapped_column(Integer)

    shariah_cert_ref: Mapped[str | None] = mapped_column(String(120))
    external_ref: Mapped[str | None] = mapped_column(String(120))
    instruction_id: Mapped[int | None] = mapped_column(Integer)
    is_placeholder: Mapped[bool] = mapped_column(nullable=False, default=False)
    status: Mapped[HoldingStatus] = mapped_column(nullable=False, default=HoldingStatus.PENDING)

    @property
    def accrual_nominal_scale(self) -> Decimal:
        """Sukuk pay profit on nominal, not on what was paid for them."""
        if self.asset_class is AssetClass.SUKUK and self.nominal and self.face_amount:
            return self.nominal / self.face_amount
        return Decimal(1)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Holding {self.id} {self.asset_class} {self.currency} {self.face_amount}>"
