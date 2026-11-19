import type { Metadata } from "next";

import { StatusPill } from "@/components/ui/StatusPill";
import { Banner, Card, EmptyState, PageHeader } from "@/components/ui/primitives";
import { apiFetch } from "@/lib/api/server";
import type { AccountRow } from "@/lib/api/schema";
import { humanise } from "@/lib/format";

export const metadata: Metadata = { title: "Chart of accounts" };

const TYPE_ORDER = ["ASSET", "LIABILITY", "EQUITY", "INCOME", "EXPENSE"] as const;
const TYPE_LABEL: Record<string, string> = {
  ASSET: "Assets",
  LIABILITY: "Liabilities",
  EQUITY: "Equity",
  INCOME: "Income",
  EXPENSE: "Expenses",
};

/**
 * Read-only: the chart is loaded from finance's own CSV and changed the same way,
 * not edited here. This screen exists so anyone can see what a role or a posting
 * rule resolves a code to, without going to the seed file.
 */
export default async function AccountsPage() {
  const accounts = await apiFetch<AccountRow[]>("/accounts");
  const proposed = accounts.filter((account) => account.is_proposed);

  const byType = new Map<string, AccountRow[]>();
  for (const account of accounts) {
    const list = byType.get(account.type) ?? [];
    list.push(account);
    byType.set(account.type, list);
  }
  const types = [
    ...TYPE_ORDER.filter((type) => byType.has(type)),
    ...[...byType.keys()].filter((type) => !(TYPE_ORDER as readonly string[]).includes(type)),
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Chart of accounts"
        description="Every account a posting can resolve to. Business code asks for a role, never an account code directly -- this is the table that role mapping resolves against."
      />

      {proposed.length > 0 && (
        <Banner tone="warning" title={`${proposed.length} account${proposed.length === 1 ? "" : "s"} proposed, not yet approved`}>
          Flagged accounts support fair-value postings but are still awaiting
          finance&rsquo;s formal sign-off (see the README&rsquo;s open decisions).
          Postable, but not yet confirmed as permanent.
        </Banner>
      )}

      {accounts.length === 0 ? (
        <EmptyState title="No accounts loaded" />
      ) : (
        types.map((type) => (
          <Card key={type} title={TYPE_LABEL[type] ?? humanise(type)} bodyClassName="px-0 py-0">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-ground">
                  <tr className="text-xs tracking-wide text-muted uppercase">
                    <th scope="col" className="px-5 py-2">
                      Code
                    </th>
                    <th scope="col" className="px-3 py-2">
                      Name
                    </th>
                    <th scope="col" className="px-3 py-2">
                      Normal balance
                    </th>
                    <th scope="col" className="px-3 py-2">
                      Report
                    </th>
                    <th scope="col" className="px-3 py-2">
                      Currency
                    </th>
                    <th scope="col" className="px-3 py-2">
                      Postable
                    </th>
                    <th scope="col" className="px-3 py-2">
                      Needs a holding
                    </th>
                    <th scope="col" className="px-5 py-2">
                      Status
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {(byType.get(type) ?? []).map((account) => (
                    <tr key={account.code} className="border-t border-border">
                      <td className="tnum px-5 py-2.5 font-medium">{account.code}</td>
                      <td className="px-3 py-2.5">
                        {account.name}
                        {account.is_proposed && (
                          <span className="ml-2 text-xs text-warning-ink">proposed</span>
                        )}
                      </td>
                      <td className="px-3 py-2.5 text-muted">{humanise(account.normal_balance)}</td>
                      <td className="px-3 py-2.5 text-muted">{account.report}</td>
                      <td className="px-3 py-2.5 text-muted">{account.currency ?? "—"}</td>
                      <td className="px-3 py-2.5 text-muted">
                        {account.is_postable ? "Yes" : "Heading only"}
                      </td>
                      <td className="px-3 py-2.5 text-muted">
                        {account.needs_holding ? "Yes" : "—"}
                      </td>
                      <td className="px-5 py-2.5">
                        <StatusPill state={account.status} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        ))
      )}
    </div>
  );
}
