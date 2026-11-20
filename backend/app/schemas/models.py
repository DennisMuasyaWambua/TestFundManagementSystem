"""Request and response schemas for every endpoint."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import Field

from app.enums import (
    AssetClass,
    BatchStatus,
    HoldingStatus,
    InstructionStatus,
    InstructionType,
    KycStatus,
    LedgerEvent,
    ProfitTreatment,
    RecordStatus,
    RiskRating,
    UserRole,
)
from app.schemas.common import Money, Rate, Schema

# --- Auth --------------------------------------------------------------------


class LoginRequest(Schema):
    username: str
    password: str
    totp: str | None = None


class LoginResponse(Schema):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    must_change_password: bool
    mfa_enrolment_required: bool
    user: MeResponse


class ChangePasswordRequest(Schema):
    current_password: str
    new_password: str


class MfaEnrolResponse(Schema):
    secret: str
    provisioning_uri: str


class MfaVerifyRequest(Schema):
    code: str


class MeResponse(Schema):
    id: str
    name: str
    title: str
    email: str
    role: UserRole
    permissions: list[str]
    client_access: list[str] | None = None
    mfa_enrolled: bool
    must_change_password: bool


# --- Users -------------------------------------------------------------------


class UserRow(Schema):
    id: str
    name: str
    title: str
    email: str
    role: UserRole
    active: bool
    mfa_enrolled: bool
    must_change_password: bool
    last_login: datetime | None = None
    client_access: list[str] = []


class CreateUserRequest(Schema):
    id: str = Field(min_length=3, max_length=32)
    name: str
    title: str = ""
    email: str
    role: UserRole
    client_access: list[str] = []


class CreateUserResponse(Schema):
    user: UserRow
    temporary_password: str


class UpdateUserRequest(Schema):
    name: str | None = None
    title: str | None = None
    email: str | None = None
    role: UserRole | None = None
    client_access: list[str] | None = None


# --- Reference ---------------------------------------------------------------


class AccountRow(Schema):
    code: str
    name: str
    type: str
    parent_code: str | None = None
    is_postable: bool
    normal_balance: str
    report: str
    needs_holding: bool
    currency: str | None = None
    is_proposed: bool
    status: RecordStatus


class RoleMappingRow(Schema):
    client_id: str
    role: str
    account_code: str


class FxRateRow(Schema):
    id: int
    currency: str
    base_currency: str
    rate_date: date
    rate: Rate
    source: str
    entered_by: str


class CreateFxRateRequest(Schema):
    currency: str = Field(min_length=3, max_length=3)
    base_currency: str = Field(min_length=3, max_length=3)
    rate_date: date
    rate: Rate
    source: str = "CBK indicative mean"


# --- Clients -----------------------------------------------------------------


class CustodyAccountRow(Schema):
    id: str
    client_id: str
    custodian: str
    custodian_address: str
    custodian_contact: str
    account_number: str
    currency: str
    cash_ledger_code: str
    wakala_ledger_code: str
    custody_agreement_ref: str | None = None
    is_default: bool
    status: RecordStatus


class CreateCustodyAccountRequest(Schema):
    id: str
    custodian: str
    custodian_address: str = ""
    custodian_contact: str = "The Custody Manager"
    account_number: str
    currency: str = Field(min_length=3, max_length=3)
    cash_ledger_code: str
    wakala_ledger_code: str
    custody_agreement_ref: str | None = None
    is_default: bool = False


class MandateFeeRow(Schema):
    asset_class: AssetClass
    fee_pct_of_income: Rate
    effective_from: date


class SetMandateFeesRequest(Schema):
    fees: list[MandateFeeRow]


class ClientRow(Schema):
    id: str
    legal_name: str
    base_currency: str
    kyc_status: KycStatus
    kyc_reviewed_on: date | None = None
    aml_risk_rating: RiskRating | None = None
    agreement_ref: str | None = None
    agreement_date: date | None = None
    final_wht_rate: Rate
    status: RecordStatus
    onboarding_gaps: list[str] = []


class CreateClientRequest(Schema):
    id: str = Field(min_length=2, max_length=32)
    legal_name: str
    base_currency: str = Field(min_length=3, max_length=3)
    agreement_ref: str | None = None
    agreement_date: date | None = None
    final_wht_rate: Rate = "0"  # type: ignore[assignment]


class UpdateClientRequest(Schema):
    legal_name: str | None = None
    agreement_ref: str | None = None
    agreement_date: date | None = None
    final_wht_rate: Rate | None = None
    status: RecordStatus | None = None


class KycRequest(Schema):
    kyc_status: KycStatus
    aml_risk_rating: RiskRating | None = None
    reviewed_on: date | None = None
    note: str = ""


# --- Opening balances --------------------------------------------------------


class CreateBatchRequest(Schema):
    client_id: str
    cutover_date: date
    profit_treatment: ProfitTreatment = ProfitTreatment.CLIENT_PROFIT_ONLY
    pro_rata_accrual_split: bool = False


class UpdateCutoverDateRequest(Schema):
    cutover_date: date


class UpdateClientRequest(Schema):
    client_id: str


class BatchRow(Schema):
    id: int
    client_id: str
    cutover_date: date
    profit_treatment: ProfitTreatment
    pro_rata_accrual_split: bool
    status: BatchStatus
    prepared_by: str
    approved_by: str | None = None
    warnings_acknowledged_by: str | None = None
    warnings_acknowledged_note: str | None = None
    rejection_reason: str | None = None
    journal_entry_id: int | None = None
    source_files: dict[str, Any] = {}


class FindingRow(Schema):
    level: str
    code: str
    message: str
    row: int | None = None


class ValidationReportBody(Schema):
    ok: bool
    errors: list[FindingRow] = []
    warnings: list[FindingRow] = []
    totals: dict[str, str] = {}


class PreviewLineRow(Schema):
    account_code: str
    account_name: str
    holding_id: str | None = None
    currency: str
    debit: Money
    credit: Money
    description: str
    derived: bool


class PreviewBody(Schema):
    batch_id: int
    client_id: str
    cutover_date: date
    lines: list[PreviewLineRow]
    total_debit: Money
    total_credit: Money
    section_a: Money
    section_b: Money
    suspense: Money
    balanced: bool
    reconciles: bool
    holdings: list[dict[str, Any]]
    validation: ValidationReportBody | None = None


class BatchDetail(Schema):
    batch: BatchRow
    validation: ValidationReportBody | None = None
    preview: PreviewBody | None = None


class AcknowledgeWarningsRequest(Schema):
    note: str = Field(min_length=10)


class ReasonRequest(Schema):
    reason: str = Field(min_length=3)


class BatchPostedResponse(Schema):
    batch: BatchRow
    journal_entry_id: int
    holdings_created: int
    reconciliation_breaks: int
    locked_through: date


# --- Holdings ----------------------------------------------------------------


class HoldingRow(Schema):
    id: str
    client_id: str
    asset_class: AssetClass
    custody_account_id: str
    currency: str
    counterparty: str
    related_party: bool
    description: str
    face_amount: Money
    nominal: Money | None = None
    profit_rate: Rate | None = None
    day_basis: int
    start_date: date | None = None
    maturity_date: date | None = None
    monthly_rent: Money | None = None
    accrual_start: date | None = None
    opening_accrued: Money
    shariah_cert_ref: str | None = None
    external_ref: str | None = None
    is_placeholder: bool
    status: HoldingStatus


class HoldingBalances(Schema):
    outstanding: Money
    accrued_profit: Money
    rent_receivable: Money
    fair_value_adjustment: Money
    fair_value: Money
    income_recognised: Money
    fee_charged: Money
    profit_to_date: Money


class HoldingListRow(Schema):
    """A holding plus the balances the grid shows.

    The balances always come from the ledger, never from the holding record: a
    holding row stores terms, not money.
    """

    holding: HoldingRow
    balances: HoldingBalances


class HoldingDetail(Schema):
    holding: HoldingRow
    balances: HoldingBalances
    valuations: list[ValuationRow] = []
    journal: list[JournalEntryRow] = []


class ReceiptRequest(Schema):
    value_date: date
    advice_ref: str = Field(min_length=1)


class ContributionRequest(ReceiptRequest):
    client_id: str
    custody_account_id: str
    amount: Money
    narrative: str = ""


class ProfitReceiptRequest(ReceiptRequest):
    gross: Money
    wht: Money = "0.00"  # type: ignore[assignment]


class PrincipalReceiptRequest(ReceiptRequest):
    amount: Money


class MaturityRequest(ReceiptRequest):
    principal: Money
    profit: Money
    wht: Money = "0.00"  # type: ignore[assignment]


class RentReceiptRequest(ReceiptRequest):
    gross: Money
    wht: Money = "0.00"  # type: ignore[assignment]


class TenantDepositRequest(ReceiptRequest):
    amount: Money


class WriteOffRequest(Schema):
    on: date
    reason: str = Field(min_length=3)


class ReceiptResponse(Schema):
    journal_entry_id: int
    holding_id: str | None = None
    true_up: Money


# --- Instructions ------------------------------------------------------------


class CheckRow(Schema):
    key: str
    label: str
    passed: bool
    detail: str = ""


class ApprovalRow(Schema):
    user_id: str
    user_name: str = ""
    title: str = ""
    approved_at: datetime


class InstructionRow(Schema):
    id: int
    reference: str
    client_id: str
    custody_account_id: str
    type: InstructionType
    holding_id: str | None = None
    amount: Money
    currency: str
    value_date: date
    beneficiary: str
    beneficiary_account: str
    narrative: str
    client_instruction_ref: str | None = None
    params: dict[str, Any] = {}
    status: InstructionStatus
    maker_id: str
    letter_pdf_sha256: str | None = None
    signed_copy_sha256: str | None = None
    sent_at: datetime | None = None
    custodian_confirmation_ref: str | None = None
    settled_on: date | None = None
    journal_entry_id: int | None = None
    rejection_reason: str | None = None
    approvals: list[ApprovalRow] = []


class InstructionDetail(Schema):
    instruction: InstructionRow
    checks: list[CheckRow] = []
    holding: HoldingRow | None = None
    journal: JournalEntryRow | None = None
    can_approve: bool = False
    can_dispatch: bool = False
    can_settle: bool = False


class CreateInstructionRequest(Schema):
    client_id: str
    custody_account_id: str
    type: InstructionType
    amount: Money
    value_date: date
    beneficiary: str = ""
    beneficiary_account: str = ""
    narrative: str = ""
    client_instruction_ref: str | None = None
    params: dict[str, Any] = {}


class SettleInstructionRequest(Schema):
    confirmation_ref: str = Field(min_length=1)
    settled_on: date
    amount: Money


class CashPositionRow(Schema):
    custody_account_id: str
    currency: str
    ledger: Money
    committed: Money
    available: Money


# --- Valuations --------------------------------------------------------------


class ValuationRow(Schema):
    id: int
    holding_id: str
    client_id: str
    valuation_date: date
    price: Rate | None = None
    value: Money
    source: str
    valuer_name: str | None = None
    report_ref: str | None = None
    status: str
    prepared_by: str
    approved_by: str | None = None
    rejection_reason: str | None = None
    journal_entry_id: int | None = None


class CreateValuationRequest(Schema):
    holding_id: str
    valuation_date: date
    source: str = Field(min_length=3)
    price: Rate | None = None
    value: Money | None = None
    valuer_name: str | None = None
    report_ref: str | None = None
    report_file_id: int | None = None


# --- Period end --------------------------------------------------------------


class AccrualLineRow(Schema):
    holding_id: str
    profit_target: Money
    profit_booked: Money
    profit_posted: Money
    fee_target: Money
    fee_booked: Money
    fee_posted: Money


class AccrualRunResponse(Schema):
    client_id: str
    as_of: date
    lines: list[AccrualLineRow]
    rent_invoices: list[str]
    skipped: list[str]
    profit_posted: Money
    fee_posted: Money
    changed: bool


class RevaluationLineRow(Schema):
    account_code: str
    holding_id: str | None = None
    currency: str
    own_amount: Money
    base_before: Money
    base_after: Money
    delta: Money


class RevaluationResponse(Schema):
    client_id: str
    as_of: date
    lines: list[RevaluationLineRow]
    net: Money
    changed: bool


class ChecklistItemRow(Schema):
    key: str
    label: str
    done: bool
    detail: str = ""
    blocking: bool = False


class ChecklistResponse(Schema):
    client_id: str
    period_end: date
    items: list[ChecklistItemRow]
    can_close: bool


class CloseRequest(Schema):
    override_reason: str | None = None


class CloseResponse(Schema):
    client_id: str
    period_end: date
    net_profit: Money
    journal_entry_id: int | None = None
    locked_through: date
    already_closed: bool


# --- Reconciliation ----------------------------------------------------------


class CustodianBalanceRequest(Schema):
    custody_account_id: str
    as_of: date
    balance: Money
    statement_ref: str = ""
    source_file_id: int | None = None


class CustodianPositionRequest(Schema):
    holding_id: str
    as_of: date
    amount: Money
    statement_ref: str = ""
    source_file_id: int | None = None


class ReconLineRow(Schema):
    scope: str
    key: str
    label: str
    currency: str
    ledger: str
    custodian: str | None = None
    difference: str
    matched: bool
    note: str = ""


class ReconResponse(Schema):
    run_id: int | None = None
    as_of: date
    client_id: str | None = None
    lines: list[ReconLineRow]
    breaks: int


class ReconRunRow(Schema):
    id: int
    client_id: str | None = None
    as_of: date
    scope: str
    performed_by: str
    performed_at: datetime
    breaks: int


# --- Ledger ------------------------------------------------------------------


class JournalLineRow(Schema):
    id: int
    account_code: str
    client_id: str
    holding_id: str | None = None
    amount: Money
    currency: str
    fx_rate: Rate
    base_amount: Money
    description: str


class JournalEntryRow(Schema):
    id: int
    entry_date: date
    event: LedgerEvent
    client_id: str
    currency: str
    reference: str | None = None
    narrative: str
    instruction_id: int | None = None
    reverses_id: int | None = None
    batch_id: int | None = None
    created_by: str
    created_at: datetime
    lines: list[JournalLineRow] = []


class ManualJournalLine(Schema):
    account_code: str
    holding_id: str | None = None
    currency: str | None = None
    debit: Money = "0.00"  # type: ignore[assignment]
    credit: Money = "0.00"  # type: ignore[assignment]
    description: str = ""


class ManualJournalRequest(Schema):
    client_id: str
    entry_date: date
    narrative: str = Field(min_length=3)
    lines: list[ManualJournalLine] = Field(min_length=2)


class ManualJournalRow(Schema):
    id: int
    client_id: str
    entry_date: date
    narrative: str
    status: str
    prepared_by: str
    approved_by: str | None = None
    journal_entry_id: int | None = None
    lines: list[ManualJournalLine] = []


# --- Reports -----------------------------------------------------------------


class ReportLineRow(Schema):
    code: str
    name: str
    amount: Money


class TrialBalanceRow(Schema):
    code: str
    name: str
    type: str
    debit: Money
    credit: Money


class TrialBalanceResponse(Schema):
    as_of: date
    client_id: str | None = None
    rows: list[TrialBalanceRow]
    total_debit: Money
    total_credit: Money
    balanced: bool


class SectionTotalRow(Schema):
    label: str
    lines: list[ReportLineRow]
    total: Money


class BalanceSheetResponse(Schema):
    client_id: str
    client: str
    currency: str
    as_of: date
    assets: SectionTotalRow
    liabilities: SectionTotalRow
    client_funds: SectionTotalRow
    retained_result: Money


class ProfitAndLossResponse(Schema):
    client_id: str
    client: str
    currency: str
    from_date: date
    to_date: date
    income: SectionTotalRow
    expenses: SectionTotalRow
    net_profit: Money


class YourAccountRow(Schema):
    capital_brought_forward: Money
    capital_movements: Money
    profit_brought_forward: Money
    profit_earned_closed: Money
    profit_paid: Money
    profit_open_period: Money
    fees_charged: Money
    profit_other_movements: Money
    your_balance: Money


class WhereHeldRow(Schema):
    assets: list[ReportLineRow]
    less_payables: list[ReportLineRow]
    net_holdings: Money


class StatementHoldingRow(Schema):
    id: str
    asset_class: str
    currency: str
    outstanding: Money
    accrued_profit: Money
    fair_value_adjustment: Money
    profit_rate: Rate | None = None
    maturity_date: date | None = None
    status: str


class StatementResponse(Schema):
    client: str
    client_id: str
    currency: str
    from_date: date
    to_date: date
    your_account: YourAccountRow
    where_held: WhereHeldRow
    holdings: list[StatementHoldingRow]
    reconciles: bool
    held_reason: str | None = None


class PortfolioRowOut(Schema):
    client_id: str
    client: str
    asset_class: str
    count: int
    cost: Money
    fair_value: Money
    accrued_profit: Money


class PortfolioCashOut(Schema):
    client_id: str
    custodian: str
    account_number: str
    currency: str
    balance: Money
    base_amount: Money


class PortfolioSummaryResponse(Schema):
    as_of: date
    number_of_clients: int
    rows: list[PortfolioRowOut]
    cash: list[PortfolioCashOut]
    totals: dict[str, Money]


class DashboardClientRow(Schema):
    client_id: str
    client: str
    currency: str
    net_asset_value: Money
    reconciles: bool
    held_reason: str | None = None
    suspense: Money
    locked_through: date | None = None
    kyc_status: str


class MaturityRowOut(Schema):
    holding_id: str
    client_id: str
    counterparty: str
    currency: str
    outstanding: Money
    maturity_date: date
    days: int


class DashboardResponse(Schema):
    as_of: date
    clients: list[DashboardClientRow]
    aum_by_asset_class: dict[str, Money]
    awaiting_my_action: list[dict[str, Any]]
    reconciliation_breaks: list[str]
    maturities_30: list[MaturityRowOut]
    maturities_90: list[MaturityRowOut]
    suspense_total: Money
    instructions_in_progress: list[dict[str, Any]]


HoldingDetail.model_rebuild()
InstructionDetail.model_rebuild()
LoginResponse.model_rebuild()
