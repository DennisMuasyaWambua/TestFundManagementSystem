import type { Metadata } from "next";
import Link from "next/link";

import { Money, RateBadge } from "@/components/money/Money";
import { StatusPill } from "@/components/ui/StatusPill";
import { Card, EmptyState, PageHeader } from "@/components/ui/primitives";
import { apiFetch } from "@/lib/api/server";
import type { HoldingListRow } from "@/lib/api/schema";
import { formatDate, humanise, todayIso } from "@/lib/format";

export const metadata: Metadata = { title: "Holdings" };

const ASSET_CLASSES = ["WAKALA", "SUKUK", "PRIVATE_FINANCING", "PROPERTY"] as const;
const STATUSES = ["PENDING", "ACTIVE", "MATURED", "WRITTEN_OFF", "CANCELLED"] as const;

export default async function HoldingsPage({
  searchParams,
}: {
  searchParams: Promise<{
    client?: string;
    asset_class?: string;
    status?: string;
    maturing?: string;
    by?: string;
  }>;
}) {
  const filters = await searchParams;
  const today = todayIso();

  const rows = await apiFetch<HoldingListRow[]>("/holdings", {
    query: {
      client: filters.client ?? null,
      asset_class: filters.asset_class ?? null,
      status: filters.status ?? null,
      as_of: todayIso(),
    },
  });

  // "Maturing within" is a view of the same rows, not another query: either a
  // day-count preset, or an exact calendar date, whichever the user picked. A
  // specific date is the more precise choice, so it wins when both are set.
  const cutoff = filters.by || null;
  const horizon = filters.maturing ? Number(filters.maturing) : null;
  const visible = rows.filter(({ holding }) => {
    if (cutoff === null && horizon === null) return true;
    if (!holding.maturity_date) return false;
    if (cutoff !== null) return holding.maturity_date <= cutoff;
    return horizon !== null && (daysUntil(holding.maturity_date) ?? Infinity) <= horizon;
  });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Holdings"
        description="Every investment across every mandate. Balances are read from the ledger, never stored on the holding."
      />

      <Card title="Filters" bodyClassName="px-5 py-4">
        <form className="grid grid-cols-1 gap-4 sm:grid-cols-6">
          <label className="text-sm">
            <span className="text-xs font-medium tracking-wide text-muted uppercase">
              Client
            </span>
            <input
              name="client"
              defaultValue={filters.client ?? ""}
              placeholder="All clients"
              className="mt-1 w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm"
            />
          </label>
          <label className="text-sm">
            <span className="text-xs font-medium tracking-wide text-muted uppercase">
              Asset class
            </span>
            <select
              name="asset_class"
              defaultValue={filters.asset_class ?? ""}
              className="mt-1 w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm"
            >
              <option value="">All</option>
              {ASSET_CLASSES.map((value) => (
                <option key={value} value={value}>
                  {humanise(value)}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            <span className="text-xs font-medium tracking-wide text-muted uppercase">
              Status
            </span>
            <select
              name="status"
              defaultValue={filters.status ?? ""}
              className="mt-1 w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm"
            >
              <option value="">All</option>
              {STATUSES.map((value) => (
                <option key={value} value={value}>
                  {humanise(value)}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            <span className="text-xs font-medium tracking-wide text-muted uppercase">
              Maturing within
            </span>
            <select
              name="maturing"
              defaultValue={filters.by ? "" : filters.maturing ?? ""}
              className="mt-1 w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm"
            >
              <option value="">Any time</option>
              <option value="30">30 days</option>
              <option value="90">90 days</option>
              <option value="180">180 days</option>
            </select>
          </label>
          <label className="text-sm">
            <span className="text-xs font-medium tracking-wide text-muted uppercase">
              Maturing by
            </span>
            <input
              type="date"
              name="by"
              min={today}
              defaultValue={filters.by ?? ""}
              className="mt-1 w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-ink"
            />
          </label>
          <div className="flex items-end gap-2">
            <button
              type="submit"
              className="btn w-full rounded-lg bg-accent px-4 py-2 text-sm font-medium text-accent-ink hover:bg-accent-hover"
            >
              Apply
            </button>
            {(filters.maturing || filters.by) && (
              <Link
                href={{
                  pathname: "/holdings",
                  query: {
                    ...(filters.client ? { client: filters.client } : {}),
                    ...(filters.asset_class ? { asset_class: filters.asset_class } : {}),
                    ...(filters.status ? { status: filters.status } : {}),
                  },
                }}
                className="btn flex items-center rounded-lg bg-surface px-3 py-2 text-sm font-medium text-ink ring-1 ring-border ring-inset hover:bg-ground"
              >
                Clear
              </Link>
            )}
          </div>
        </form>
      </Card>

      <Card
        bodyClassName="px-0 py-0"
        description={
          cutoff
            ? `Maturing on or before ${formatDate(cutoff)}.`
            : horizon
              ? `Maturing within ${horizon} days.`
              : undefined
        }
      >
        {visible.length === 0 ? (
          <div className="p-5">
            <EmptyState title="No holdings match these filters" />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-ground">
                <tr className="text-xs tracking-wide text-muted uppercase">
                  <th scope="col" className="px-5 py-2">
                    Deal
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Counterparty
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Currency
                  </th>
                  <th scope="col" className="px-3 py-2 text-right">
                    Outstanding
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Rate
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Matures
                  </th>
                  <th scope="col" className="px-3 py-2 text-right">
                    Accrued
                  </th>
                  <th scope="col" className="px-3 py-2 text-right">
                    Fair value adj.
                  </th>
                  <th scope="col" className="px-5 py-2">
                    Status
                  </th>
                </tr>
              </thead>
              <tbody>
                {visible.map(({ holding, balances }) => {
                  const days = holding.maturity_date ? daysUntil(holding.maturity_date) : null;
                  return (
                    <tr key={holding.id} className="border-t border-border">
                      <td className="px-5 py-2.5">
                        <Link
                          href={`/holdings/${encodeURIComponent(holding.id)}`}
                          className="font-medium text-accent underline"
                        >
                          {holding.id}
                        </Link>
                        <p className="text-xs text-muted">
                          {holding.client_id} · {humanise(holding.asset_class)}
                        </p>
                      </td>
                      <td className="px-3 py-2.5 text-muted">
                        {holding.counterparty}
                        {holding.related_party && (
                          <span className="ml-1 text-xs text-warning-ink">(related party)</span>
                        )}
                      </td>
                      <td className="px-3 py-2.5">{holding.currency}</td>
                      <td className="px-3 py-2.5 text-right">
                        <Money amount={balances.outstanding} />
                      </td>
                      <td className="px-3 py-2.5">
                        <RateBadge rate={holding.profit_rate} />
                      </td>
                      <td className="px-3 py-2.5 text-muted">
                        {formatDate(holding.maturity_date)}
                        {days !== null && days >= 0 && days <= 30 && (
                          <p className="text-xs text-warning-ink">in {days} days</p>
                        )}
                      </td>
                      <td className="px-3 py-2.5 text-right">
                        <Money amount={balances.accrued_profit} muteZero />
                      </td>
                      <td className="px-3 py-2.5 text-right">
                        <Money amount={balances.fair_value_adjustment} muteZero colour />
                      </td>
                      <td className="px-5 py-2.5">
                        <StatusPill state={holding.status} />
                        {holding.is_placeholder && (
                          <p className="mt-1 text-xs text-warning-ink">terms pending</p>
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

/**
 * Whole days from today to an ISO date.
 *
 * Both ends are read as UTC midnight, so the answer cannot drift by a day with the
 * viewer's timezone -- which matters when the figure decides whether a maturity is
 * flagged as imminent.
 */
function daysUntil(iso: string): number | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!match) return null;
  const target = Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  const now = new Date();
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.round((target - today) / 86_400_000);
}
