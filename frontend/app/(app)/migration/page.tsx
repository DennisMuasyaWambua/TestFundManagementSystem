import type { Metadata } from "next";
import Link from "next/link";

import { StatusPill } from "@/components/ui/StatusPill";
import { ButtonLink, Card, EmptyState, PageHeader } from "@/components/ui/primitives";
import { apiFetch } from "@/lib/api/server";
import type { BatchRow } from "@/lib/api/schema";
import { requireUser } from "@/lib/auth/me";
import { PERMISSION, can } from "@/lib/auth/permissions";
import { formatDate, humanise } from "@/lib/format";

export const metadata: Metadata = { title: "Opening balances" };

export default async function MigrationPage() {
  const me = await requireUser();
  const batches = await apiFetch<BatchRow[]>("/opening-balances");

  return (
    <div className="space-y-6">
      <PageHeader
        title="Opening balance migration"
        description="The one-off load of what each client already holds. Nothing reaches the ledger until a second person approves the batch."
        actions={
          can(me, PERMISSION.openingBalancePrepare) && (
            <ButtonLink href="/migration/new" variant="primary">
              New batch
            </ButtonLink>
          )
        }
      />

      <Card bodyClassName="px-0 py-0">
        {batches.length === 0 ? (
          <div className="p-5">
            <EmptyState
              title="No batches yet"
              description="A batch stages one client's position as at the cutover date, from the old system and the custodian's statements."
            />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-ground">
                <tr className="text-xs tracking-wide text-muted uppercase">
                  <th scope="col" className="px-5 py-2">
                    Batch
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Client
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Cutover
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Profit treatment
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Prepared by
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Approved by
                  </th>
                  <th scope="col" className="px-5 py-2">
                    Status
                  </th>
                </tr>
              </thead>
              <tbody>
                {batches.map((batch) => (
                  <tr key={batch.id} className="border-t border-border">
                    <td className="px-5 py-2.5">
                      <Link
                        href={`/migration/${batch.id}`}
                        className="tnum font-medium text-accent underline"
                      >
                        #{batch.id}
                      </Link>
                    </td>
                    <td className="px-3 py-2.5">
                      <Link href={`/clients/${batch.client_id}`} className="underline">
                        {batch.client_id}
                      </Link>
                    </td>
                    <td className="px-3 py-2.5">{formatDate(batch.cutover_date)}</td>
                    <td className="px-3 py-2.5 text-muted">
                      {batch.profit_treatment === "CLIENT_PROFIT_ONLY"
                        ? "Client profit only"
                        : "Includes year-to-date P&L"}
                      {batch.pro_rata_accrual_split && (
                        <p className="text-xs text-warning-ink">accrual split pro rata</p>
                      )}
                    </td>
                    <td className="px-3 py-2.5 text-muted">{batch.prepared_by}</td>
                    <td className="px-3 py-2.5 text-muted">{batch.approved_by ?? "—"}</td>
                    <td className="px-5 py-2.5">
                      <StatusPill state={batch.status} />
                      {batch.status === "REJECTED" && batch.rejection_reason && (
                        <p className="mt-1 max-w-[16rem] text-xs text-muted">
                          {batch.rejection_reason}
                        </p>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title="How a batch becomes a ledger entry">
        <ol className="space-y-2 text-sm text-muted">
          {[
            ["Draft", "Finance creates the batch and uploads the four CSVs. Rows are staged."],
            ["Validated", "Every check in the specification runs. Errors block; warnings must be acknowledged in writing."],
            ["Submitted", "The preparer submits, having seen the journal and the statement as they will be."],
            ["Approved", "Finance head or signatory approves."],
            ["Posted", "One opening entry dated the cutover, holdings created, and the reconciliation run."],
          ].map(([state, text], index) => (
            <li key={state} className="flex gap-3">
              <span className="tnum shrink-0 font-medium text-ink">{index + 1}.</span>
              <span>
                <span className="font-medium text-ink">{humanise(state)}</span> — {text}
              </span>
            </li>
          ))}
        </ol>
      </Card>
    </div>
  );
}
