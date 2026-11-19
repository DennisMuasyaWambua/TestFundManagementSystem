import type { Metadata } from "next";
import Link from "next/link";

import { ValuationDecision } from "@/app/(app)/valuations/ValuationDecision";
import { Money } from "@/components/money/Money";
import { StatusPill } from "@/components/ui/StatusPill";
import { Banner, Card, EmptyState, PageHeader } from "@/components/ui/primitives";
import { apiFetch } from "@/lib/api/server";
import type { ValuationRow } from "@/lib/api/schema";
import { requireUser } from "@/lib/auth/me";
import { PERMISSION, can } from "@/lib/auth/permissions";
import { formatDate } from "@/lib/format";

export const metadata: Metadata = { title: "Valuations" };

export default async function ValuationsPage() {
  const me = await requireUser();
  const valuations = await apiFetch<ValuationRow[]>("/valuations", { query: { limit: 200 } });

  const pending = valuations.filter((row) => row.status === "PENDING");
  const decided = valuations.filter((row) => row.status !== "PENDING");

  return (
    <div className="space-y-6">
      <PageHeader
        title="Valuations"
        description="Sukuk are priced per 100 of nominal; investment property is valued by an independent valuer. Cost is never overwritten — the difference goes to a fair value adjustment account."
      />

      {!can(me, PERMISSION.valuationApprove) && pending.length > 0 && (
        <Banner tone="info" title="Approval is a finance or signatory decision">
          You can see what is pending, but approving a valuation needs a finance or
          signatory role — and never the person who proposed it.
        </Banner>
      )}

      <Card
        title={`Waiting for approval (${pending.length})`}
        description="Nothing is posted until a second person approves."
        bodyClassName="px-0 py-0"
      >
        {pending.length === 0 ? (
          <div className="p-5">
            <EmptyState title="Nothing is waiting" />
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
                    Valued at
                  </th>
                  <th scope="col" className="px-3 py-2 text-right">
                    Value
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Basis
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Proposed by
                  </th>
                  <th scope="col" className="px-5 py-2">
                    Decision
                  </th>
                </tr>
              </thead>
              <tbody>
                {pending.map((valuation) => (
                  <tr key={valuation.id} className="border-t border-border">
                    <td className="px-5 py-3">
                      <Link
                        href={`/holdings/${encodeURIComponent(valuation.holding_id)}`}
                        className="font-medium text-accent underline"
                      >
                        {valuation.holding_id}
                      </Link>
                      <p className="text-xs text-muted">{valuation.client_id}</p>
                    </td>
                    <td className="px-3 py-3">{formatDate(valuation.valuation_date)}</td>
                    <td className="px-3 py-3 text-right">
                      <Money amount={valuation.value} />
                      {valuation.price && (
                        <p className="tnum text-xs text-muted">{valuation.price} per 100</p>
                      )}
                    </td>
                    <td className="px-3 py-3 text-muted">
                      <p>{valuation.source}</p>
                      {valuation.valuer_name && (
                        <p className="text-xs">
                          {valuation.valuer_name}
                          {valuation.report_ref ? ` · ${valuation.report_ref}` : ""}
                        </p>
                      )}
                    </td>
                    <td className="px-3 py-3 text-muted">{valuation.prepared_by}</td>
                    <td className="px-5 py-3">
                      {can(me, PERMISSION.valuationApprove) ? (
                        <ValuationDecision valuation={valuation} />
                      ) : (
                        <StatusPill state="PENDING" />
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title="Decided" bodyClassName="px-0 py-0">
        {decided.length === 0 ? (
          <div className="p-5">
            <EmptyState title="No valuation has been decided yet" />
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
                    Valued at
                  </th>
                  <th scope="col" className="px-3 py-2 text-right">
                    Value
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Proposed / approved
                  </th>
                  <th scope="col" className="px-5 py-2">
                    Status
                  </th>
                </tr>
              </thead>
              <tbody>
                {decided.map((valuation) => (
                  <tr key={valuation.id} className="border-t border-border">
                    <td className="px-5 py-2.5">
                      <Link
                        href={`/holdings/${encodeURIComponent(valuation.holding_id)}`}
                        className="font-medium text-accent underline"
                      >
                        {valuation.holding_id}
                      </Link>
                    </td>
                    <td className="px-3 py-2.5">{formatDate(valuation.valuation_date)}</td>
                    <td className="px-3 py-2.5 text-right">
                      <Money amount={valuation.value} />
                    </td>
                    <td className="px-3 py-2.5 text-muted">
                      {valuation.prepared_by} / {valuation.approved_by ?? "—"}
                    </td>
                    <td className="px-5 py-2.5">
                      <StatusPill state={valuation.status} />
                      {valuation.rejection_reason && (
                        <p className="mt-1 max-w-[16rem] text-xs text-muted">
                          {valuation.rejection_reason}
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
    </div>
  );
}
