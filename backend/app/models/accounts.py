"""Chart of accounts and the role mapping that keeps account codes out of business code."""

from __future__ import annotations

from sqlalchemy import Boolean, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import AccountType, MutableMixin, NormalBalance, RecordStatus, ReportSection


class Account(Base, MutableMixin):
    __tablename__ = "accounts"

    code: Mapped[str] = mapped_column(String(10), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    type: Mapped[AccountType] = mapped_column(nullable=False)
    parent_code: Mapped[str | None] = mapped_column(String(10))
    is_postable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    normal_balance: Mapped[NormalBalance] = mapped_column(nullable=False)
    report: Mapped[ReportSection] = mapped_column(nullable=False)
    needs_holding: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    currency: Mapped[str | None] = mapped_column(String(3))
    sub_ledger: Mapped[str | None] = mapped_column(String(32))
    is_proposed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    """Open decision 9: added to the chart but awaiting finance sign-off."""
    status: Mapped[RecordStatus] = mapped_column(nullable=False, default=RecordStatus.ACTIVE)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Account {self.code} {self.name}>"


class RoleMapping(Base, MutableMixin):
    """Resolves a posting role to an account code, per client or for all clients."""

    __tablename__ = "role_mappings"
    __table_args__ = (UniqueConstraint("client_id", "role", name="uq_role_mapping"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(32), nullable=False, default="*")
    role: Mapped[str] = mapped_column(String(48), nullable=False)
    account_code: Mapped[str] = mapped_column(String(10), nullable=False)
