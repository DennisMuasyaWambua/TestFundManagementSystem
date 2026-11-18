"""Every enumerated value in the domain.

Kept in its own module with no imports from the rest of the application so that
``app.db`` can map each enum to a column type without an import cycle.
"""

from __future__ import annotations

from enum import StrEnum

SYSTEM_USER = "system"


# --- Chart of accounts -------------------------------------------------------


class AccountType(StrEnum):
    ASSET = "ASSET"
    LIABILITY = "LIABILITY"
    EQUITY = "EQUITY"
    INCOME = "INCOME"
    EXPENSE = "EXPENSE"


class NormalBalance(StrEnum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class ReportSection(StrEnum):
    BS = "BS"
    PL = "PL"


NORMAL_BALANCE_BY_TYPE = {
    AccountType.ASSET: NormalBalance.DEBIT,
    AccountType.EXPENSE: NormalBalance.DEBIT,
    AccountType.LIABILITY: NormalBalance.CREDIT,
    AccountType.EQUITY: NormalBalance.CREDIT,
    AccountType.INCOME: NormalBalance.CREDIT,
}

REPORT_BY_TYPE = {
    AccountType.ASSET: ReportSection.BS,
    AccountType.LIABILITY: ReportSection.BS,
    AccountType.EQUITY: ReportSection.BS,
    AccountType.INCOME: ReportSection.PL,
    AccountType.EXPENSE: ReportSection.PL,
}


# --- People ------------------------------------------------------------------


class UserRole(StrEnum):
    MAKER = "MAKER"
    SIGNATORY = "SIGNATORY"
    FINANCE = "FINANCE"
    COMPLIANCE = "COMPLIANCE"
    ADMIN = "ADMIN"


# --- Clients -----------------------------------------------------------------


class KycStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"


class RiskRating(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class RecordStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    CLOSED = "CLOSED"


# --- Holdings ----------------------------------------------------------------


class AssetClass(StrEnum):
    WAKALA = "WAKALA"
    SUKUK = "SUKUK"
    PRIVATE_FINANCING = "PRIVATE_FINANCING"
    PROPERTY = "PROPERTY"


class HoldingStatus(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    MATURED = "MATURED"
    WRITTEN_OFF = "WRITTEN_OFF"
    CANCELLED = "CANCELLED"


# --- Instructions ------------------------------------------------------------


class InstructionType(StrEnum):
    PLACE_WAKALA = "PLACE_WAKALA"
    BUY_SUKUK = "BUY_SUKUK"
    DISBURSE_FINANCING = "DISBURSE_FINANCING"
    PURCHASE_PROPERTY = "PURCHASE_PROPERTY"
    PAY_CLIENT_PROFIT = "PAY_CLIENT_PROFIT"
    RETURN_CAPITAL = "RETURN_CAPITAL"
    PAY_MGMT_FEE = "PAY_MGMT_FEE"
    PAY_CUSTODY_FEE = "PAY_CUSTODY_FEE"
    FX_CONVERSION = "FX_CONVERSION"


INVESTMENT_INSTRUCTIONS = {
    InstructionType.PLACE_WAKALA: AssetClass.WAKALA,
    InstructionType.BUY_SUKUK: AssetClass.SUKUK,
    InstructionType.DISBURSE_FINANCING: AssetClass.PRIVATE_FINANCING,
    InstructionType.PURCHASE_PROPERTY: AssetClass.PROPERTY,
}


class InstructionStatus(StrEnum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    SENT = "SENT"
    SETTLED = "SETTLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


PIPELINE_STATUSES = (
    InstructionStatus.PENDING_APPROVAL,
    InstructionStatus.APPROVED,
    InstructionStatus.SENT,
)


# --- Workflow states ---------------------------------------------------------


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class BatchStatus(StrEnum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    POSTED = "POSTED"
    REJECTED = "REJECTED"


class ProfitTreatment(StrEnum):
    """Open decision 2: how current-year profit is loaded at migration."""

    CLIENT_PROFIT_ONLY = "CLIENT_PROFIT_ONLY"
    INCLUDE_PL = "INCLUDE_PL"


class FileKind(StrEnum):
    SIGNED_LETTER = "SIGNED_LETTER"
    CUSTODIAN_STATEMENT = "CUSTODIAN_STATEMENT"
    VALUER_REPORT = "VALUER_REPORT"
    OPENING_BALANCE_CSV = "OPENING_BALANCE_CSV"
    OTHER = "OTHER"


# --- Ledger events -----------------------------------------------------------


class LedgerEvent(StrEnum):
    OPENING_BALANCE = "OPENING_BALANCE"
    CLIENT_CONTRIBUTION = "CLIENT_CONTRIBUTION"
    CAPITAL_WITHDRAWAL = "CAPITAL_WITHDRAWAL"
    INVESTMENT_PLACED = "INVESTMENT_PLACED"
    PROFIT_ACCRUED = "PROFIT_ACCRUED"
    FEE_ACCRUED = "FEE_ACCRUED"
    PROFIT_RECEIVED = "PROFIT_RECEIVED"
    PRINCIPAL_RECEIVED = "PRINCIPAL_RECEIVED"
    INVESTMENT_MATURED = "INVESTMENT_MATURED"
    RENT_INVOICED = "RENT_INVOICED"
    RENT_RECEIVED = "RENT_RECEIVED"
    TENANT_DEPOSIT_RECEIVED = "TENANT_DEPOSIT_RECEIVED"
    FINANCING_WRITE_OFF = "FINANCING_WRITE_OFF"
    FAIR_VALUE_REVALUATION = "FAIR_VALUE_REVALUATION"
    FX_REVALUATION = "FX_REVALUATION"
    FX_CONVERSION = "FX_CONVERSION"
    MONTH_END_CLOSE = "MONTH_END_CLOSE"
    PROFIT_PAID_TO_CLIENT = "PROFIT_PAID_TO_CLIENT"
    MGMT_FEE_PAID = "MGMT_FEE_PAID"
    CUSTODY_FEE_PAID = "CUSTODY_FEE_PAID"
    MANUAL = "MANUAL"
    REVERSAL = "REVERSAL"
