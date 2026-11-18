/**
 * What the signed-in user may do, as reported by `GET /me`.
 *
 * This decides what the UI *shows*.  It never decides what happens: the API enforces
 * every permission and answers 403, and the screens are built to display that answer.
 * Hiding a button the user cannot use is a courtesy, not a control.
 */

import type { Me, Permission, UserRole } from "@/lib/api/schema";

export const PERMISSION = {
  instructionCreate: "INSTRUCTION_CREATE",
  instructionApprove: "INSTRUCTION_APPROVE",
  instructionDispatch: "INSTRUCTION_DISPATCH",
  receiptRecord: "RECEIPT_RECORD",
  ledgerOperations: "LEDGER_OPERATIONS",
  valuationPropose: "VALUATION_PROPOSE",
  valuationApprove: "VALUATION_APPROVE",
  openingBalancePrepare: "OPENING_BALANCE_PREPARE",
  openingBalanceApprove: "OPENING_BALANCE_APPROVE",
  custodianStatementRecord: "CUSTODIAN_STATEMENT_RECORD",
  reconciliationRun: "RECONCILIATION_RUN",
  reportsView: "REPORTS_VIEW",
  auditView: "AUDIT_VIEW",
  usersManage: "USERS_MANAGE",
  clientOnboarding: "CLIENT_ONBOARDING",
  journalView: "JOURNAL_VIEW",
  fxRatesManage: "FX_RATES_MANAGE",
} as const satisfies Record<string, Permission>;

export type PermissionName = (typeof PERMISSION)[keyof typeof PERMISSION];

export function can(me: Me | null, permission: PermissionName): boolean {
  if (!me) return false;
  return me.permissions.includes(permission);
}

export function canAny(me: Me | null, ...permissions: PermissionName[]): boolean {
  return permissions.some((permission) => can(me, permission));
}

export function hasRole(me: Me | null, ...roles: UserRole[]): boolean {
  return me !== null && roles.includes(me.role);
}

/** Whether this user may see a given client's data at all (CoB reg 15). */
export function canSeeClient(me: Me | null, clientId: string): boolean {
  if (!me) return false;
  // An empty or absent list means "all clients".
  if (!me.client_access || me.client_access.length === 0) return true;
  return me.client_access.includes(clientId);
}

export const ROLE_LABEL: Record<UserRole, string> = {
  MAKER: "Operations (maker)",
  SIGNATORY: "Authorised signatory",
  FINANCE: "Finance",
  COMPLIANCE: "Compliance",
  ADMIN: "Administrator",
};
