/**
 * Named aliases for the generated OpenAPI schemas.
 *
 * `types/api.d.ts` is generated from `backend/openapi.json` (`npm run generate:api`)
 * and is never edited by hand.  This file is the only place that reaches into it, so
 * a renamed backend schema breaks here -- in one file, at compile time -- instead of
 * in thirty page components.
 */

import type { components } from "@/types/api";

type S = components["schemas"];

// --- identity and permissions ------------------------------------------------
export type Me = S["MeResponse"];
export type UserRole = S["UserRole"];
export type Permission = Me["permissions"][number];
export type UserRow = S["UserRow"];
export type LoginResponse = S["LoginResponse"];
export type MfaEnrolResponse = S["MfaEnrolResponse"];

// --- dashboard ---------------------------------------------------------------
export type Dashboard = S["DashboardResponse"];
export type DashboardClientRow = S["DashboardClientRow"];
export type MaturityRow = S["MaturityRowOut"];

// --- clients -----------------------------------------------------------------
export type ClientRow = S["ClientRow"];
export type CustodyAccountRow = S["CustodyAccountRow"];
export type MandateFeeRow = S["MandateFeeRow"];
export type KycStatus = S["KycStatus"];
export type RiskRating = S["RiskRating"];
export type RecordStatus = S["RecordStatus"];
export type RoleMappingRow = S["RoleMappingRow"];
export type AccountRow = S["AccountRow"];

// --- statements and reports --------------------------------------------------
export type Statement = S["StatementResponse"];
export type StatementHoldingRow = S["StatementHoldingRow"];
export type YourAccountRow = S["YourAccountRow"];
export type WhereHeldRow = S["WhereHeldRow"];
export type TrialBalance = S["TrialBalanceResponse"];
export type TrialBalanceRow = S["TrialBalanceRow"];
export type BalanceSheet = S["BalanceSheetResponse"];
export type ProfitAndLoss = S["ProfitAndLossResponse"];
export type ReportLineRow = S["ReportLineRow"];
export type SectionTotalRow = S["SectionTotalRow"];
export type PortfolioSummary = S["PortfolioSummaryResponse"];
export type PortfolioRow = S["PortfolioRowOut"];
export type PortfolioCash = S["PortfolioCashOut"];

// --- holdings and receipts ---------------------------------------------------
export type HoldingRow = S["HoldingRow"];
export type HoldingListRow = S["HoldingListRow"];
export type HoldingDetail = S["HoldingDetail"];
export type HoldingBalances = S["HoldingBalances"];
export type HoldingStatus = S["HoldingStatus"];
export type AssetClass = S["AssetClass"];
export type ReceiptResponse = S["ReceiptResponse"];

// --- instructions ------------------------------------------------------------
export type InstructionRow = S["InstructionRow"];
export type InstructionDetail = S["InstructionDetail"];
export type InstructionType = S["InstructionType"];
export type InstructionStatus = S["InstructionStatus"];
export type CheckRow = S["CheckRow"];
export type ApprovalRow = S["ApprovalRow"];
export type CashPositionRow = S["CashPositionRow"];

// --- opening balance migration ----------------------------------------------
export type BatchRow = S["BatchRow"];
export type BatchDetail = S["BatchDetail"];
export type BatchStatus = S["BatchStatus"];
export type BatchPosted = S["BatchPostedResponse"];
export type FindingRow = S["FindingRow"];
export type PreviewLineRow = S["PreviewLineRow"];
export type PreviewBody = S["PreviewBody"];
export type ValidationReportBody = S["ValidationReportBody"];
export type ProfitTreatment = S["ProfitTreatment"];

// --- period end, FX, valuations, reconciliation ------------------------------
export type Checklist = S["ChecklistResponse"];
export type ChecklistItemRow = S["ChecklistItemRow"];
export type CloseResponse = S["CloseResponse"];
export type AccrualRun = S["AccrualRunResponse"];
export type AccrualLineRow = S["AccrualLineRow"];
export type Revaluation = S["RevaluationResponse"];
export type RevaluationLineRow = S["RevaluationLineRow"];
export type FxRateRow = S["FxRateRow"];
export type ValuationRow = S["ValuationRow"];
export type ReconResponse = S["ReconResponse"];
export type ReconLineRow = S["ReconLineRow"];
export type ReconRunRow = S["ReconRunRow"];

// --- ledger and audit --------------------------------------------------------
export type JournalEntryRow = S["JournalEntryRow"];
export type JournalLineRow = S["JournalLineRow"];
export type ManualJournalRow = S["ManualJournalRow"];
export type LedgerEvent = S["LedgerEvent"];
export type AuditEntry = S["AuditEntry"];
export type JournalPage = S["Page_JournalEntryRow_"];
export type AuditPage = S["Page_AuditEntry_"];
