"""Clients, their custody accounts and their mandate fee rates."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, RateT
from app.models.base import AssetClass, KycStatus, MutableMixin, RecordStatus, RiskRating


class Client(Base, MutableMixin):
    __tablename__ = "clients"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    legal_name: Mapped[str] = mapped_column(String(200), nullable=False)
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    kyc_status: Mapped[KycStatus] = mapped_column(nullable=False, default=KycStatus.PENDING)
    kyc_reviewed_on: Mapped[date | None] = mapped_column(Date)
    aml_risk_rating: Mapped[RiskRating | None] = mapped_column()
    agreement_ref: Mapped[str | None] = mapped_column(String(80))
    agreement_date: Mapped[date | None] = mapped_column(Date)
    final_wht_rate: Mapped[Decimal] = mapped_column(RateT, nullable=False, default=Decimal("0"))
    status: Mapped[RecordStatus] = mapped_column(nullable=False, default=RecordStatus.ACTIVE)

    @property
    def onboarding_gaps(self) -> list[str]:
        """What is still missing before this client may be instructed on."""
        gaps: list[str] = []
        if self.kyc_status is not KycStatus.APPROVED:
            gaps.append(f"KYC status is {self.kyc_status}, not APPROVED")
        if not self.agreement_ref:
            gaps.append("no investment management agreement reference on file")
        if self.status is not RecordStatus.ACTIVE:
            gaps.append(f"client status is {self.status}")
        return gaps


class CustodyAccount(Base, MutableMixin):
    __tablename__ = "custody_accounts"
    __table_args__ = (UniqueConstraint("account_number", "currency", name="uq_custody_account"),)

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    client_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    custodian: Mapped[str] = mapped_column(String(160), nullable=False)
    custodian_address: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    custodian_contact: Mapped[str] = mapped_column(
        String(160), nullable=False, default="The Custody Manager"
    )
    account_number: Mapped[str] = mapped_column(String(64), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    cash_ledger_code: Mapped[str] = mapped_column(String(10), nullable=False)
    wakala_ledger_code: Mapped[str] = mapped_column(String(10), nullable=False)
    custody_agreement_ref: Mapped[str | None] = mapped_column(String(80))
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[RecordStatus] = mapped_column(nullable=False, default=RecordStatus.ACTIVE)


class MandateFee(Base, MutableMixin):
    """Management fee rate history, by client and asset class, per open decision 6."""

    __tablename__ = "mandate_fees"
    __table_args__ = (
        UniqueConstraint("client_id", "asset_class", "effective_from", name="uq_mandate_fee"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    asset_class: Mapped[AssetClass] = mapped_column(nullable=False)
    fee_pct_of_income: Mapped[Decimal] = mapped_column(RateT, nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
