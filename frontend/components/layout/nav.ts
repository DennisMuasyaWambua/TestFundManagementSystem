/** The navigation, with the permission each entry needs. */

import { PERMISSION, type PermissionName } from "@/lib/auth/permissions";

export type NavItem = {
  href: string;
  label: string;
  /** Visible when the user holds any one of these; absent means everyone. */
  permissions?: PermissionName[];
};

export type NavGroup = { heading: string; items: NavItem[] };

export const NAV: NavGroup[] = [
  {
    heading: "Overview",
    items: [
      { href: "/dashboard", label: "Dashboard" },
      { href: "/clients", label: "Clients" },
      { href: "/holdings", label: "Holdings" },
      { href: "/accounts", label: "Chart of accounts" },
    ],
  },
  {
    heading: "Money",
    items: [
      {
        href: "/instructions",
        label: "Custody instructions",
      },
      {
        href: "/receipts/new",
        label: "Record a receipt",
        permissions: [PERMISSION.receiptRecord],
      },
      { href: "/valuations", label: "Valuations" },
      {
        href: "/fx-rates",
        label: "Exchange rates",
        permissions: [PERMISSION.fxRatesManage],
      },
    ],
  },
  {
    heading: "Control",
    items: [
      {
        href: "/reconciliation",
        label: "Reconciliation",
        permissions: [PERMISSION.reconciliationRun, PERMISSION.custodianStatementRecord],
      },
      {
        href: "/close",
        label: "Month-end close",
        permissions: [PERMISSION.ledgerOperations],
      },
      {
        href: "/migration",
        label: "Opening balances",
        permissions: [PERMISSION.openingBalancePrepare, PERMISSION.openingBalanceApprove],
      },
      {
        href: "/journal",
        label: "Journal",
        permissions: [PERMISSION.journalView],
      },
    ],
  },
  {
    heading: "Reporting",
    items: [
      { href: "/reports", label: "Reports", permissions: [PERMISSION.reportsView] },
      { href: "/audit", label: "Audit log", permissions: [PERMISSION.auditView] },
    ],
  },
  {
    heading: "Administration",
    items: [
      { href: "/admin/users", label: "Users", permissions: [PERMISSION.usersManage] },
      { href: "/settings/profile", label: "My profile" },
    ],
  },
];
