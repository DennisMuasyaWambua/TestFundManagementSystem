import type { Metadata } from "next";

import { ReconciliationPanel } from "@/app/(app)/reconciliation/ReconciliationPanel";
import { Banner, Card, EmptyState, PageHeader } from "@/components/ui/primitives";
import { apiFetch } from "@/lib/api/server";
import type {
  ClientRow,
  CustodyAccountRow,
  HoldingListRow,
  ReconRunRow,
} from "@/lib/api/schema";
import { formatDate, formatDateTime, todayIso } from "@/lib/format";

export const metadata: Metadata = { title: "Reconciliation" };

export default async function ReconciliationPage({
  searchParams,
}: {
  searchParams: Promise<{ as_of?: string }>;
}) {
  const { as_of } = await searchParams;
  const asOf = as_of ?? todayIso();

  const [clients, holdings, runs] = await Promise.all([
    apiFetch<ClientRow[]>("/clients"),
    apiFetch<HoldingListRow[]>("/holdings", { query: { status: "ACTIVE" } }),
    apiFetch<ReconRunRow[]>("/reconciliations", { query: { limit: 25 } }),
  ]);

  const custodyAccounts: CustodyAccountRow[] = (
    await Promise.all(
      clients.map((client) =>
        apiFetch<CustodyAccountRow[]>(
          `/clients/${encodeURIComponent(client.id)}/custody-accounts`,
        ),
      ),
    )
  ).flat();

  return (
    <div className="space-y-6">
      <PageHeader
        title="Reconciliation"
        description="Our ledger against the custodians' own records: cash every day, positions every month."
        actions={
          <form className="flex items-end gap-2">
            <label className="text-xs text-muted">
              <span className="block">As at</span>
              <input
                type="date"
                name="as_of"
                defaultValue={asOf}
                className="mt-1 rounded-lg border border-border bg-surface px-3 py-2 text-sm text-ink"
              />
            </label>
            <button
              type="submit"
              className="btn rounded-lg bg-surface px-4 py-2 text-sm font-medium text-ink ring-1 ring-border ring-inset hover:bg-ground"
            >
              Show
            </button>
          </form>
        }
      />

      <Banner tone="info" title="Who may run this">
        A reconciliation may not be performed by someone who authorises payments
        (Conduct of Business reg 29(5)-(7)). Finance and compliance can run it; an
        authorised signatory cannot, and the API refuses the attempt.
      </Banner>

      <ReconciliationPanel
        clients={clients}
        custodyAccounts={custodyAccounts}
        holdings={holdings}
        asOf={asOf}
      />

      <Card
        title="Previous runs"
        description="Each run is kept with who performed it, when, and how many breaks it found."
        bodyClassName="px-0 py-0"
      >
        {runs.length === 0 ? (
          <div className="p-5">
            <EmptyState title="No reconciliation has been run yet" />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-ground">
                <tr className="text-xs tracking-wide text-muted uppercase">
                  <th scope="col" className="px-5 py-2">
                    Run
                  </th>
                  <th scope="col" className="px-3 py-2">
                    As at
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Client
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Scope
                  </th>
                  <th scope="col" className="px-3 py-2 text-right">
                    Breaks
                  </th>
                  <th scope="col" className="px-5 py-2">
                    Performed by
                  </th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr key={run.id} className="border-t border-border">
                    <td className="tnum px-5 py-2.5 font-medium">#{run.id}</td>
                    <td className="px-3 py-2.5">{formatDate(run.as_of)}</td>
                    <td className="px-3 py-2.5 text-muted">{run.client_id ?? "all mandates"}</td>
                    <td className="px-3 py-2.5 text-muted">{run.scope.toLowerCase()}</td>
                    <td className="px-3 py-2.5 text-right">
                      <span
                        className={
                          run.breaks === 0
                            ? "tnum text-success-ink"
                            : "tnum font-medium text-danger-ink"
                        }
                      >
                        {run.breaks}
                      </span>
                    </td>
                    <td className="px-5 py-2.5 text-muted">
                      {run.performed_by}
                      <p className="text-xs">{formatDateTime(run.performed_at)}</p>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
