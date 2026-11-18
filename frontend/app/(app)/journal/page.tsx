import type { Metadata } from "next";
import Link from "next/link";

import { ReverseEntry } from "@/app/(app)/journal/ReverseEntry";
import { Money } from "@/components/money/Money";
import { Banner, Card, EmptyState, PageHeader } from "@/components/ui/primitives";
import { apiFetch, apiFetchOrNull } from "@/lib/api/server";
import type { ClientRow, JournalEntryRow, JournalPage } from "@/lib/api/schema";
import { requireUser } from "@/lib/auth/me";
import { PERMISSION, can } from "@/lib/auth/permissions";
import { formatDate, formatDateTime, humanise } from "@/lib/format";
import { formatRate } from "@/lib/money";

export const metadata: Metadata = { title: "Journal" };

export default async function JournalPage({
  searchParams,
}: {
  searchParams: Promise<{
    client?: string;
    from?: string;
    to?: string;
    account?: string;
    holding?: string;
    event?: string;
    entry?: string;
  }>;
}) {
  const me = await requireUser();
  const filters = await searchParams;

  const [clients, page, entry] = await Promise.all([
    apiFetch<ClientRow[]>("/clients"),
    apiFetch<JournalPage>("/journal", {
      query: {
        client: filters.client ?? null,
        from: filters.from ?? null,
        to: filters.to ?? null,
        account: filters.account ?? null,
        holding: filters.holding ?? null,
        event: filters.event ?? null,
        limit: 100,
      },
    }),
    filters.entry
      ? apiFetchOrNull<JournalEntryRow>(`/journal/${encodeURIComponent(filters.entry)}`)
      : Promise.resolve(null),
  ]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Journal"
        description="Every posting ever made. Entries are append-only: a mistake is corrected by a reversal plus a new correct entry, never by an edit."
      />

      <Banner tone="info" title="Why nothing here can be edited">
        The journal and audit tables reject UPDATE and DELETE in the database itself,
        not merely in the application. That is what makes the record defensible seven
        years later.
      </Banner>

      <Card title="Search" bodyClassName="px-5 py-4">
        <form className="grid grid-cols-1 gap-4 sm:grid-cols-3 lg:grid-cols-6">
          <label className="text-sm">
            <span className="text-xs font-medium tracking-wide text-muted uppercase">
              Client
            </span>
            <select
              name="client"
              defaultValue={filters.client ?? ""}
              className="mt-1 w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm"
            >
              <option value="">All</option>
              {clients.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.id}
                </option>
              ))}
            </select>
          </label>
          {(
            [
              ["from", "From", "date"],
              ["to", "To", "date"],
              ["account", "Account", "text"],
              ["holding", "Holding", "text"],
            ] as const
          ).map(([name, label, type]) => (
            <label key={name} className="text-sm">
              <span className="text-xs font-medium tracking-wide text-muted uppercase">
                {label}
              </span>
              <input
                name={name}
                type={type}
                defaultValue={filters[name] ?? ""}
                className="mt-1 w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm"
              />
            </label>
          ))}
          <div className="flex items-end">
            <button
              type="submit"
              className="btn w-full rounded-lg bg-accent px-4 py-2 text-sm font-medium text-accent-ink hover:bg-accent-hover"
            >
              Search
            </button>
          </div>
        </form>
      </Card>

      {entry && (
        <Card
          title={`Entry #${entry.id}`}
          description={`${humanise(entry.event)} · ${formatDate(entry.entry_date)} · ${entry.narrative}`}
          bodyClassName="px-0 py-0"
          actions={
            can(me, PERMISSION.ledgerOperations) && !entry.reverses_id ? (
              <ReverseEntry entry={entry} />
            ) : null
          }
        >
          <div className="px-5 py-3 text-xs text-muted">
            Posted by {entry.created_by} at {formatDateTime(entry.created_at)}
            {entry.reference ? ` · reference ${entry.reference}` : ""}
            {entry.instruction_id ? ` · instruction #${entry.instruction_id}` : ""}
            {entry.batch_id ? ` · migration batch #${entry.batch_id}` : ""}
            {entry.reverses_id ? ` · reverses entry #${entry.reverses_id}` : ""}
          </div>
          <div className="overflow-x-auto border-t border-border">
            <table className="w-full text-sm">
              <thead className="bg-ground">
                <tr className="text-xs tracking-wide text-muted uppercase">
                  <th scope="col" className="px-5 py-2">
                    Account
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Holding
                  </th>
                  <th scope="col" className="px-3 py-2 text-right">
                    Amount
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Currency
                  </th>
                  <th scope="col" className="px-3 py-2 text-right">
                    Rate
                  </th>
                  <th scope="col" className="px-5 py-2 text-right">
                    Base amount
                  </th>
                </tr>
              </thead>
              <tbody>
                {(entry.lines ?? []).map((line) => (
                  <tr key={line.id} className="border-t border-border">
                    <td className="px-5 py-2.5">
                      <span className="tnum font-medium">{line.account_code}</span>
                      <p className="text-xs text-muted">{line.description}</p>
                    </td>
                    <td className="px-3 py-2.5 text-muted">{line.holding_id ?? "—"}</td>
                    <td className="px-3 py-2.5 text-right">
                      <Money amount={line.amount} colour />
                    </td>
                    <td className="px-3 py-2.5">{line.currency}</td>
                    <td className="tnum px-3 py-2.5 text-right">{formatRate(line.fx_rate)}</td>
                    <td className="px-5 py-2.5 text-right">
                      <Money amount={line.base_amount} colour />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="border-t border-border px-5 py-3 text-xs text-muted">
            A debit is positive and a credit is negative. Each entry sums to zero in its
            own currency and to zero in the client&rsquo;s base currency.
          </p>
        </Card>
      )}

      <Card
        title={`Entries (${page.total})`}
        description={`Showing ${page.items.length}, newest first.`}
        bodyClassName="px-0 py-0"
      >
        {page.items.length === 0 ? (
          <div className="p-5">
            <EmptyState title="No entry matches this search" />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-ground">
                <tr className="text-xs tracking-wide text-muted uppercase">
                  <th scope="col" className="px-5 py-2">
                    Entry
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Date
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Client
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Event
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Narrative
                  </th>
                  <th scope="col" className="px-5 py-2">
                    Posted by
                  </th>
                </tr>
              </thead>
              <tbody>
                {page.items.map((row) => (
                  <tr key={row.id} className="border-t border-border">
                    <td className="px-5 py-2.5">
                      <Link
                        href={`/journal?entry=${row.id}`}
                        className="tnum font-medium text-accent underline"
                      >
                        #{row.id}
                      </Link>
                      {row.reverses_id && (
                        <p className="text-xs text-warning-ink">reversal</p>
                      )}
                    </td>
                    <td className="px-3 py-2.5">{formatDate(row.entry_date)}</td>
                    <td className="px-3 py-2.5 text-muted">{row.client_id}</td>
                    <td className="px-3 py-2.5">{humanise(row.event)}</td>
                    <td className="px-3 py-2.5 text-muted">{row.narrative}</td>
                    <td className="px-5 py-2.5 text-muted">{row.created_by}</td>
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
