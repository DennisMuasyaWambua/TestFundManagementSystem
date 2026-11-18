import type { Metadata } from "next";

import { Card, EmptyState, PageHeader } from "@/components/ui/primitives";
import { apiFetch } from "@/lib/api/server";
import type { AuditPage } from "@/lib/api/schema";
import { formatDateTime, humanise } from "@/lib/format";

export const metadata: Metadata = { title: "Audit log" };

export default async function AuditLogPage({
  searchParams,
}: {
  searchParams: Promise<{ user?: string; entity?: string; from?: string; to?: string }>;
}) {
  const filters = await searchParams;

  const page = await apiFetch<AuditPage>("/audit-log", {
    query: {
      user: filters.user ?? null,
      entity: filters.entity ?? null,
      from: filters.from ?? null,
      to: filters.to ?? null,
      limit: 200,
    },
  });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Audit log"
        description="Every state change, sign-in, failure, approval and posting. Append-only, kept for at least seven years."
      />

      <Card title="Search" bodyClassName="px-5 py-4">
        <form className="grid grid-cols-1 gap-4 sm:grid-cols-5">
          {(
            [
              ["user", "User", "text"],
              ["entity", "Entity", "text"],
              ["from", "From", "date"],
              ["to", "To", "date"],
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

      <Card
        title={`${page.total} entries`}
        description={`Showing ${page.items.length}, newest first.`}
        bodyClassName="px-0 py-0"
      >
        {page.items.length === 0 ? (
          <div className="p-5">
            <EmptyState title="Nothing matches this search" />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-ground">
                <tr className="text-xs tracking-wide text-muted uppercase">
                  <th scope="col" className="px-5 py-2">
                    When
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Who
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Action
                  </th>
                  <th scope="col" className="px-3 py-2">
                    On what
                  </th>
                  <th scope="col" className="px-5 py-2">
                    Detail
                  </th>
                </tr>
              </thead>
              <tbody>
                {page.items.map((row) => (
                  <tr key={row.id} className="border-t border-border align-top">
                    <td className="px-5 py-2.5 whitespace-nowrap">{formatDateTime(row.at)}</td>
                    <td className="px-3 py-2.5">
                      {row.user_id}
                      {row.ip && <p className="text-xs text-muted">{row.ip}</p>}
                    </td>
                    <td className="px-3 py-2.5 font-medium">{humanise(row.action)}</td>
                    <td className="px-3 py-2.5 text-muted">
                      {row.entity}
                      {row.entity_id ? ` #${row.entity_id}` : ""}
                      {row.client_id && <p className="text-xs">{row.client_id}</p>}
                    </td>
                    <td className="px-5 py-2.5">
                      {row.detail && Object.keys(row.detail).length > 0 ? (
                        <dl className="space-y-0.5 text-xs">
                          {Object.entries(row.detail).map(([key, value]) => (
                            <div key={key} className="flex gap-2">
                              <dt className="shrink-0 text-muted">{humanise(key)}:</dt>
                              <dd className="min-w-0 break-words">
                                {typeof value === "object"
                                  ? JSON.stringify(value)
                                  : String(value)}
                              </dd>
                            </div>
                          ))}
                        </dl>
                      ) : (
                        <span className="text-muted">—</span>
                      )}
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
