import type { Metadata } from "next";
import Link from "next/link";

import { ClientsOverview } from "@/app/(app)/dashboard/ClientsOverview";
import { Money } from "@/components/money/Money";
import { StatusPill } from "@/components/ui/StatusPill";
import {
  Banner,
  ButtonLink,
  Card,
  EmptyState,
  PageHeader,
  Stat,
} from "@/components/ui/primitives";
import { apiFetch } from "@/lib/api/server";
import type { Dashboard } from "@/lib/api/schema";
import { requireUser } from "@/lib/auth/me";
import { formatDate, pluralise, todayIso } from "@/lib/format";
import { isZero } from "@/lib/money";

export const metadata: Metadata = { title: "Dashboard" };

/** The loose dicts the dashboard endpoint returns for the two instruction lists. */
type InstructionBrief = {
  id: number;
  reference: string;
  client_id: string;
  type: string;
  amount: string;
  currency: string;
  status: string;
  value_date: string;
  approvals?: number;
};

export default async function DashboardPage({
  searchParams,
}: {
  searchParams: Promise<{ as_of?: string }>;
}) {
  const me = await requireUser();
  const { as_of } = await searchParams;
  const asOf = as_of ?? todayIso();

  const data = await apiFetch<Dashboard>("/dashboard", { query: { as_of: asOf } });

  const totalAum = Object.values(data.aum_by_asset_class);
  const awaiting = data.awaiting_my_action as unknown as InstructionBrief[];
  const inProgress = data.instructions_in_progress as unknown as InstructionBrief[];
  const nextMaturity = data.maturities_30[0] ?? data.maturities_90[0] ?? null;
  const heldClients = data.clients.filter((client) => !client.reconciles);

  return (
    <div className="space-y-6">
      <PageHeader
        title={`Good day, ${me.name.split(" ")[0] ?? me.name}`}
        description={`Position as at ${formatDate(data.as_of)}.`}
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

      {!isZero(data.suspense_total) && (
        <Banner tone="warning" title="Unreconciled balance on suspense">
          <Money amount={data.suspense_total} /> sits on suspense (1390) across all
          mandates. A client statement is held back until its own suspense balance is
          cleared by a correcting entry.
        </Banner>
      )}

      {data.reconciliation_breaks.length > 0 && (
        <Banner
          tone="danger"
          title={`${pluralise(data.reconciliation_breaks.length, "reconciliation break")}`}
        >
          <ul className="mt-1 list-inside list-disc">
            {data.reconciliation_breaks.slice(0, 5).map((text) => (
              <li key={text}>{text}</li>
            ))}
          </ul>
          <Link href="/reconciliation" className="mt-2 inline-block font-medium underline">
            Open the reconciliation screen
          </Link>
        </Banner>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="Assets under management"
          value={<Money amount={sumStrings(totalAum)} />}
          hint={`${pluralise(data.clients.length, "mandate")}, reported in USD`}
        />
        <Stat
          label="Awaiting my action"
          value={awaiting.length}
          tone={awaiting.length > 0 ? "warning" : "default"}
          hint={awaiting.length > 0 ? "Instructions in your queue" : "Your queue is clear"}
        />
        <Stat
          label="Reconciliation breaks"
          value={data.reconciliation_breaks.length}
          tone={data.reconciliation_breaks.length > 0 ? "danger" : "success"}
          hint={`As at ${formatDate(data.as_of)}`}
        />
        <Stat
          label="Next maturity"
          value={nextMaturity ? formatDate(nextMaturity.maturity_date) : "None"}
          hint={
            nextMaturity
              ? `${nextMaturity.holding_id} · ${nextMaturity.counterparty} · in ${pluralise(nextMaturity.days, "day")}`
              : "Nothing maturing within 90 days"
          }
        />
      </div>

      {awaiting.length > 0 && (
        <Card
          title="Awaiting your action"
          description="These cannot move until you act on them."
        >
          <ul className="divide-y divide-border">
            {awaiting.map((item) => (
              <li key={item.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                <div className="min-w-0">
                  <Link
                    href={`/instructions/${item.id}`}
                    className="text-sm font-medium text-accent underline"
                  >
                    {item.reference}
                  </Link>
                  <p className="text-xs text-muted">
                    {item.client_id} · {item.type.replace(/_/g, " ").toLowerCase()} · value{" "}
                    {formatDate(item.value_date)}
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <Money amount={item.amount} currency={item.currency} className="text-sm" />
                  <StatusPill state={item.status} />
                </div>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <ClientsOverview clients={data.clients} assetMix={data.aum_by_asset_class} />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card
          title="Instructions in progress"
          description="Everything not yet settled, across all mandates."
          actions={<ButtonLink href="/instructions">All instructions</ButtonLink>}
        >
          {inProgress.length === 0 ? (
            <EmptyState
              title="No instructions in flight"
              description="Nothing is waiting on a signatory, a signed letter or a custodian confirmation."
            />
          ) : (
            <ul className="divide-y divide-border">
              {inProgress.slice(0, 8).map((item) => (
                <li key={item.id} className="flex items-center justify-between gap-3 py-2.5">
                  <div className="min-w-0">
                    <Link
                      href={`/instructions/${item.id}`}
                      className="text-sm font-medium text-accent underline"
                    >
                      {item.reference}
                    </Link>
                    <p className="text-xs text-muted">
                      {item.client_id} · {item.approvals ?? 0} of 2 signatures
                    </p>
                  </div>
                  <div className="flex items-center gap-3">
                    <Money amount={item.amount} currency={item.currency} className="text-sm" />
                    <StatusPill state={item.status} />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card
          title="Maturing within 90 days"
          description="Plan the reinvestment or the payout before the value date."
        >
          {data.maturities_90.length === 0 ? (
            <EmptyState title="Nothing maturing in the next 90 days" />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-xs tracking-wide text-muted uppercase">
                    <th scope="col" className="py-2">
                      Deal
                    </th>
                    <th scope="col" className="py-2">
                      Matures
                    </th>
                    <th scope="col" className="py-2 text-right">
                      Outstanding
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {data.maturities_90.slice(0, 8).map((row) => (
                    <tr key={row.holding_id} className="border-b border-border last:border-0">
                      <td className="py-2">
                        <Link
                          href={`/holdings/${encodeURIComponent(row.holding_id)}`}
                          className="font-medium text-accent underline"
                        >
                          {row.holding_id}
                        </Link>
                        <p className="text-xs text-muted">
                          {row.client_id} · {row.counterparty}
                        </p>
                      </td>
                      <td className="py-2">
                        {formatDate(row.maturity_date)}
                        <p className="text-xs text-muted">in {pluralise(row.days, "day")}</p>
                      </td>
                      <td className="py-2 text-right">
                        <Money amount={row.outstanding} currency={row.currency} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>

      {heldClients.length > 0 && (
        <Card title="Statements on hold" description="These mandates do not yet reconcile.">
          <ul className="space-y-2">
            {heldClients.map((client) => (
              <li key={client.client_id} className="text-sm">
                <Link
                  href={`/clients/${client.client_id}/statement`}
                  className="font-medium text-accent underline"
                >
                  {client.client}
                </Link>
                <span className="text-muted">
                  {" "}
                  — {client.held_reason ?? "capital and profit do not equal net holdings"}
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

/**
 * Add a column of amounts for a headline figure.
 *
 * Done in integer cents from the string representation, so this stays exact: the
 * one place the frontend combines amounts at all, and it still never sees a float.
 */
function sumStrings(amounts: string[]): string {
  let cents = 0n;
  for (const amount of amounts) {
    const match = /^(-?)(\d+)(?:\.(\d{1,2}))?$/.exec(amount.trim());
    if (!match) continue;
    const [, sign, whole, fraction = "0"] = match;
    const value = BigInt(whole ?? "0") * 100n + BigInt((fraction + "00").slice(0, 2));
    cents += sign === "-" ? -value : value;
  }
  const negative = cents < 0n;
  const absolute = negative ? -cents : cents;
  const whole = absolute / 100n;
  const remainder = `${absolute % 100n}`.padStart(2, "0");
  return `${negative ? "-" : ""}${whole}.${remainder}`;
}
