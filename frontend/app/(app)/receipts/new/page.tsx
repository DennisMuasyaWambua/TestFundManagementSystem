import type { Metadata } from "next";
import Link from "next/link";

import { ContributionForm } from "@/app/(app)/receipts/new/ContributionForm";
import { Card, PageHeader } from "@/components/ui/primitives";
import { apiFetch } from "@/lib/api/server";
import type { ClientRow, CustodyAccountRow, HoldingListRow } from "@/lib/api/schema";
import { humanise } from "@/lib/format";

export const metadata: Metadata = { title: "Record a receipt" };

export default async function NewReceiptPage() {
  const [clients, holdings] = await Promise.all([
    apiFetch<ClientRow[]>("/clients"),
    apiFetch<HoldingListRow[]>("/holdings", { query: { status: "ACTIVE" } }),
  ]);

  const custodyByClient: Record<string, CustodyAccountRow[]> = {};
  await Promise.all(
    clients.map(async (client) => {
      custodyByClient[client.id] = await apiFetch<CustodyAccountRow[]>(
        `/clients/${encodeURIComponent(client.id)}/custody-accounts`,
      );
    }),
  );

  return (
    <div className="space-y-6">
      <PageHeader
        title="Record money received"
        description="Booked from the custodian's credit advice. A receipt needs no instruction letter, but it does need the advice reference."
      />

      <ContributionForm clients={clients} custodyByClient={custodyByClient} />

      <Card
        title="A receipt against a holding"
        description="Profit, a principal repayment, a maturity, rent or a tenant deposit is recorded on the holding itself, where its accrued balance and terms are in front of you."
      >
        {holdings.length === 0 ? (
          <p className="text-sm text-muted">No holding is active right now.</p>
        ) : (
          <ul className="divide-y divide-border">
            {holdings.map(({ holding, balances }) => (
              <li key={holding.id} className="flex flex-wrap items-center justify-between gap-3 py-2.5">
                <div className="min-w-0">
                  <Link
                    href={`/holdings/${encodeURIComponent(holding.id)}`}
                    className="text-sm font-medium text-accent underline"
                  >
                    {holding.id}
                  </Link>
                  <p className="text-xs text-muted">
                    {holding.client_id} · {humanise(holding.asset_class)} ·{" "}
                    {holding.counterparty}
                  </p>
                </div>
                <p className="tnum text-xs text-muted">
                  outstanding {holding.currency} {balances.outstanding} · accrued{" "}
                  {balances.accrued_profit}
                </p>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
