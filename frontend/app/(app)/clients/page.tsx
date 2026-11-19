import type { Metadata } from "next";
import Link from "next/link";

import { Money } from "@/components/money/Money";
import { StatusPill } from "@/components/ui/StatusPill";
import { ButtonLink, Card, EmptyState, PageHeader } from "@/components/ui/primitives";
import { apiFetch } from "@/lib/api/server";
import type { ClientRow, Dashboard } from "@/lib/api/schema";
import { requireUser } from "@/lib/auth/me";
import { PERMISSION, can } from "@/lib/auth/permissions";
import { formatDate, todayIso } from "@/lib/format";

export const metadata: Metadata = { title: "Clients" };

export default async function ClientsPage() {
  const me = await requireUser();

  // The client list carries the mandate record; the dashboard carries the live
  // valuation and the A = B outcome.  Both are needed to answer "can this client be
  // sent a statement today?", which is the question this screen exists for.
  const [clients, dashboard] = await Promise.all([
    apiFetch<ClientRow[]>("/clients"),
    apiFetch<Dashboard>("/dashboard", { query: { as_of: todayIso() } }),
  ]);

  const live = new Map(dashboard.clients.map((row) => [row.client_id, row]));

  return (
    <div className="space-y-6">
      <PageHeader
        title="Clients"
        description="One segregated mandate per client, each with its own custodian accounts, capital and profit."
        actions={
          can(me, PERMISSION.clientOnboarding) && (
            <ButtonLink href="/clients/new">New client</ButtonLink>
          )
        }
      />

      <Card bodyClassName="px-0 py-0">
        {clients.length === 0 ? (
          <div className="p-5">
            <EmptyState
              title="No mandates yet"
              description="A client is created by finance, then approved by compliance before any money can move."
            />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-ground">
                <tr className="text-xs tracking-wide text-muted uppercase">
                  <th scope="col" className="px-5 py-2">
                    Client
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Custodian
                  </th>
                  <th scope="col" className="px-3 py-2 text-right">
                    Net asset value
                  </th>
                  <th scope="col" className="px-3 py-2">
                    KYC
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Statement
                  </th>
                  <th scope="col" className="px-5 py-2">
                    Agreement
                  </th>
                </tr>
              </thead>
              <tbody>
                {clients.map((client) => {
                  const row = live.get(client.id);
                  return (
                    <tr key={client.id} className="border-t border-border">
                      <td className="px-5 py-3">
                        <Link
                          href={`/clients/${client.id}`}
                          className="font-medium text-accent underline"
                        >
                          {client.legal_name}
                        </Link>
                        <p className="text-xs text-muted">
                          {client.id} · base {client.base_currency}
                        </p>
                      </td>
                      <td className="px-3 py-3 text-muted">
                        <Link href={`/clients/${client.id}`} className="underline">
                          custody accounts
                        </Link>
                      </td>
                      <td className="px-3 py-3 text-right">
                        {row ? <Money amount={row.net_asset_value} /> : <span>—</span>}
                      </td>
                      <td className="px-3 py-3">
                        <StatusPill
                          state={client.kyc_status}
                          tone={client.kyc_status === "APPROVED" ? "success" : "warning"}
                        />
                        {client.onboarding_gaps.length > 0 && (
                          <p className="mt-1 max-w-[16rem] text-xs text-warning-ink">
                            {client.onboarding_gaps.length} onboarding gap
                            {client.onboarding_gaps.length === 1 ? "" : "s"}
                          </p>
                        )}
                      </td>
                      <td className="px-3 py-3">
                        {row === undefined ? (
                          <span className="text-muted">—</span>
                        ) : row.reconciles ? (
                          <Link href={`/clients/${client.id}/statement`}>
                            <StatusPill state="MATCHED" label="A = B" tone="success" />
                          </Link>
                        ) : (
                          <Link href={`/clients/${client.id}/statement`}>
                            <StatusPill state="HELD" label="Held" tone="warning" />
                          </Link>
                        )}
                      </td>
                      <td className="px-5 py-3 text-muted">
                        {client.agreement_ref ? (
                          <>
                            <p className="text-ink">{client.agreement_ref}</p>
                            <p className="text-xs">{formatDate(client.agreement_date)}</p>
                          </>
                        ) : (
                          <span className="text-warning-ink">not on file</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
