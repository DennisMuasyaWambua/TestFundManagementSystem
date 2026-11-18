import Link from "next/link";

import { Money } from "@/components/money/Money";
import { StatusPill } from "@/components/ui/StatusPill";
import { Card } from "@/components/ui/primitives";
import type { DashboardClientRow } from "@/lib/api/schema";
import { formatDate, humanise } from "@/lib/format";

const CLASS_LABEL: Record<string, string> = {
  WAKALA: "Wakala deposits",
  SUKUK: "Sukuk",
  PRIVATE_FINANCING: "Private financing",
  PROPERTY: "Investment property",
  CASH: "Cash at custodians",
};

/**
 * The mandate table and the asset mix.
 *
 * The A = B column is the statement test: capital plus profit owed to the client
 * must equal cash plus investments plus receivables less payables. A mandate that
 * fails it is marked here, because its statement cannot be issued.
 */
export function ClientsOverview({
  clients,
  assetMix,
}: {
  clients: DashboardClientRow[];
  assetMix: Record<string, string>;
}) {
  const mix = Object.entries(assetMix)
    .filter(([, amount]) => !/^-?0+(\.0+)?$/.test(amount))
    .sort(([, a], [, b]) => Number(b) - Number(a));
  const widths = barWidths(mix.map(([, amount]) => amount));

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
      <Card title="Mandates" className="lg:col-span-2" bodyClassName="px-0 py-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-ground">
              <tr className="text-xs tracking-wide text-muted uppercase">
                <th scope="col" className="px-5 py-2">
                  Client
                </th>
                <th scope="col" className="px-3 py-2">
                  KYC
                </th>
                <th scope="col" className="px-3 py-2 text-right">
                  Net asset value
                </th>
                <th scope="col" className="px-3 py-2">
                  Statement
                </th>
                <th scope="col" className="px-5 py-2">
                  Locked through
                </th>
              </tr>
            </thead>
            <tbody>
              {clients.map((client) => (
                <tr key={client.client_id} className="border-t border-border">
                  <td className="px-5 py-3">
                    <Link
                      href={`/clients/${client.client_id}`}
                      className="font-medium text-accent underline"
                    >
                      {client.client}
                    </Link>
                    <p className="text-xs text-muted">
                      {client.client_id} · {client.currency}
                    </p>
                  </td>
                  <td className="px-3 py-3">
                    <StatusPill
                      state={client.kyc_status}
                      tone={client.kyc_status === "APPROVED" ? "success" : "warning"}
                    />
                  </td>
                  <td className="px-3 py-3 text-right">
                    <Money amount={client.net_asset_value} />
                    {!/^-?0+(\.0+)?$/.test(client.suspense) && (
                      <p className="text-xs text-warning-ink">
                        incl. suspense <Money amount={client.suspense} />
                      </p>
                    )}
                  </td>
                  <td className="px-3 py-3">
                    {client.reconciles ? (
                      <StatusPill state="MATCHED" label="A = B" tone="success" />
                    ) : (
                      <>
                        <StatusPill state="HELD" label="Held" tone="warning" />
                        <p className="mt-1 max-w-[18rem] text-xs text-muted">
                          {client.held_reason ?? "capital and profit do not equal net holdings"}
                        </p>
                      </>
                    )}
                  </td>
                  <td className="px-5 py-3 text-muted">
                    {client.locked_through ? formatDate(client.locked_through) : "not closed"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title="Asset mix" description="By asset class, in base currency.">
        {mix.length === 0 ? (
          <p className="text-sm text-muted">Nothing is invested yet.</p>
        ) : (
          <ul className="space-y-3">
            {mix.map(([assetClass, amount], index) => (
              <li key={assetClass}>
                <div className="flex items-baseline justify-between gap-2">
                  <span className="text-sm text-ink">
                    {CLASS_LABEL[assetClass] ?? humanise(assetClass)}
                  </span>
                  <Money amount={amount} className="text-sm" />
                </div>
                <div
                  className="mt-1 h-2 overflow-hidden rounded-full bg-ground"
                  role="presentation"
                >
                  <div
                    className="h-full rounded-full bg-accent"
                    style={{ width: `${widths[index] ?? 0}%` }}
                  />
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

/**
 * Bar widths as whole percentages.
 *
 * This is the one place a figure becomes a number, and it is safe: the result is a
 * CSS width, never a balance. Nothing computed here is ever displayed as money.
 */
function barWidths(amounts: string[]): number[] {
  const values = amounts.map((amount) => Math.abs(Number(amount)) || 0);
  const largest = Math.max(...values, 1);
  return values.map((value) => Math.round((value / largest) * 100));
}
