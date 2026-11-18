"""Custody instructions: the only way money leaves a client's custody account."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, MoneyT
from app.models.base import InstructionStatus, InstructionType, TimestampMixin


class Instruction(Base, TimestampMixin):
    __tablename__ = "instructions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    reference: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    client_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    custody_account_id: Mapped[str] = mapped_column(String(48), nullable=False)
    type: Mapped[InstructionType] = mapped_column(nullable=False)
    holding_id: Mapped[str | None] = mapped_column(String(48))
    amount: Mapped[Decimal] = mapped_column(MoneyT, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    value_date: Mapped[date] = mapped_column(Date, nullable=False)
    beneficiary: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    beneficiary_account: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    narrative: Mapped[str] = mapped_column(String(600), nullable=False, default="")
    client_instruction_ref: Mapped[str | None] = mapped_column(String(120))
    params: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    status: Mapped[InstructionStatus] = mapped_column(
        nullable=False, default=InstructionStatus.PENDING_APPROVAL, index=True
    )
    maker_id: Mapped[str] = mapped_column(String(32), nullable=False)
    letter_pdf_sha256: Mapped[str | None] = mapped_column(String(64))
    signed_copy_sha256: Mapped[str | None] = mapped_column(String(64))
    signed_copy_blob_id: Mapped[int | None] = mapped_column(Integer)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    sent_by: Mapped[str | None] = mapped_column(String(32))
    custodian_confirmation_ref: Mapped[str | None] = mapped_column(String(120))
    settled_at: Mapped[datetime | None] = mapped_column(DateTime)
    settled_on: Mapped[date | None] = mapped_column(Date)
    settled_by: Mapped[str | None] = mapped_column(String(32))
    journal_entry_id: Mapped[int | None] = mapped_column(Integer)
    rejection_reason: Mapped[str | None] = mapped_column(String(400))

    approvals: Mapped[list[InstructionApproval]] = relationship(
        back_populates="instruction", lazy="selectin", order_by="InstructionApproval.id"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Instruction {self.reference} {self.type} {self.status}>"


class InstructionApproval(Base, TimestampMixin):
    __tablename__ = "instruction_approvals"
    __table_args__ = (
        UniqueConstraint("instruction_id", "user_id", name="uq_instruction_approver"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    instruction_id: Mapped[int] = mapped_column(ForeignKey("instructions.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(32), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    instruction: Mapped[Instruction] = relationship(back_populates="approvals")
