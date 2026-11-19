import type { Metadata } from "next";

import { CloseRunner } from "@/app/(app)/close/CloseRunner";
import { Card, EmptyState, PageHeader } from "@/components/ui/primitives";
import { apiFetch, apiFetchOrNull } from "@/lib/api/server";
import type { Checklist, ClientRow } from "@/lib/api/schema";
import { formatDate, previousMonthEnd } from "@/lib/format";

export const metadata: Metadata = { title: "Month-end close" };

export default async function ClosePage({
  searchParams,
}: {
  searchParams: Promise<{ period_end?: string }>;
}) {
  const { period_end } = await searchParams;
  const periodEnd = period_end ?? previousMonthEnd();

  const clients = await apiFetch<ClientRow[]>("/clients");

  const checklists = await Promise.all(
    clients.map(async (client) => ({
      client,
      checklist: await apiFetchOrNull<Checklist>(
        `/clients/${encodeURIComponent(client.id)}/close-checklist`,
        { query: { period_end: periodEnd } },
      ),
    })),
  );

  return (
    <div className="space-y-6">
      <PageHeader
        title="Month-end close"
        description="One client at a time, in a fixed order, in one transaction. Closing several months in sequence is allowed."
        actions={
          <form className="flex items-end gap-2">
            <label className="text-xs text-muted">
              <span className="block">Period end</span>
              <input
                type="date"
                name="period_end"
                defaultValue={periodEnd}
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

      <Card title="What closing does" bodyClassName="px-5 py-4">
        <ol className="space-y-1.5 text-sm text-muted">
          <li>
            <span className="font-medium text-ink">1.</span> Accrue profit, invoice rent
            and charge management fees up to {formatDate(periodEnd)}.
          </li>
          <li>
            <span className="font-medium text-ink">2.</span> Restate every
            foreign-currency balance sheet balance at the closing rate.
          </li>
          <li>
            <span className="font-medium text-ink">3.</span> Require a clean
            reconciliation, or an override with a written reason.
          </li>
          <li>
            <span className="font-medium text-ink">4.</span> Sweep the period&rsquo;s
            income and costs to the client&rsquo;s profit, in base currency.
          </li>
        </ol>
        <p className="mt-3 text-xs text-muted">
          Profit and loss reports exclude the closing entry, so each month still shows
          the income it earned and the costs it bore.
        </p>
      </Card>

      {checklists.length === 0 ? (
        <EmptyState title="No mandates to close" />
      ) : (
        checklists.map(({ client, checklist }) =>
          checklist ? (
            <CloseRunner
              key={client.id}
              client={client}
              periodEnd={periodEnd}
              initial={checklist}
            />
          ) : (
            <Card key={client.id} title={client.legal_name}>
              <p className="text-sm text-muted">
                You do not have access to this mandate&rsquo;s period end.
              </p>
            </Card>
          ),
        )
      )}
    </div>
  );
}
