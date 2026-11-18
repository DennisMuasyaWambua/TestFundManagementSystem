import type { Metadata } from "next";
import Link from "next/link";

import { Money } from "@/components/money/Money";
import { StatusPill } from "@/components/ui/StatusPill";
import { ButtonLink, Card, EmptyState, PageHeader } from "@/components/ui/primitives";
import { apiFetch } from "@/lib/api/server";
import type { InstructionRow, InstructionStatus } from "@/lib/api/schema";
import { requireUser } from "@/lib/auth/me";
import { PERMISSION, can } from "@/lib/auth/permissions";
import { formatDate, humanise } from "@/lib/format";
import { INSTRUCTION_TYPE_LABEL } from "@/lib/instructions";

export const metadata: Metadata = { title: "Custody instructions" };

const TABS: { key: string; label: string; statuses: InstructionStatus[] }[] = [
  { key: "open", label: "In progress", statuses: ["PENDING_APPROVAL", "APPROVED", "SENT"] },
  { key: "awaiting", label: "Awaiting approval", statuses: ["PENDING_APPROVAL"] },
  { key: "approved", label: "Approved, not sent", statuses: ["APPROVED"] },
  { key: "sent", label: "Sent, not confirmed", statuses: ["SENT"] },
  { key: "settled", label: "Settled", statuses: ["SETTLED"] },
  { key: "closed", label: "Rejected or cancelled", statuses: ["REJECTED", "CANCELLED"] },
];

export default async function InstructionsPage({
  searchParams,
}: {
  searchParams: Promise<{ tab?: string; client?: string }>;
}) {
  const me = await requireUser();
  const { tab, client } = await searchParams;

  // A signatory's own queue first: what they have to sign is the reason they are here.
  const defaultTab = can(me, PERMISSION.instructionApprove) ? "awaiting" : "open";
  const active = TABS.find((candidate) => candidate.key === tab) ?? TABS.find((c) => c.key === defaultTab)!;

  const all = await apiFetch<InstructionRow[]>("/instructions", {
    query: { client: client ?? null, limit: 500 },
  });
  const rows = all.filter((row) => active.statuses.includes(row.status));

  return (
    <div className="space-y-6">
      <PageHeader
        title="Custody instructions"
        description="No money leaves a custody account without a letter signed by two authorised signatories and confirmed by the custodian."
        actions={
          can(me, PERMISSION.instructionCreate) && (
            <ButtonLink href="/instructions/new" variant="primary">
              New instruction
            </ButtonLink>
          )
        }
      />

      <nav aria-label="Instruction states" className="flex flex-wrap gap-2">
        {TABS.map((candidate) => {
          const count = all.filter((row) => candidate.statuses.includes(row.status)).length;
          const isActive = candidate.key === active.key;
          return (
            <Link
              key={candidate.key}
              href={`/instructions?tab=${candidate.key}${client ? `&client=${client}` : ""}`}
              aria-current={isActive ? "page" : undefined}
              className={
                isActive
                  ? "btn inline-flex items-center gap-2 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-accent-ink"
                  : "btn inline-flex items-center gap-2 rounded-lg bg-surface px-4 py-2 text-sm font-medium text-ink ring-1 ring-border ring-inset hover:bg-ground"
              }
            >
              {candidate.label}
              <span className="tnum text-xs opacity-75">{count}</span>
            </Link>
          );
        })}
      </nav>

      <Card bodyClassName="px-0 py-0">
        {rows.length === 0 ? (
          <div className="p-5">
            <EmptyState
              title="Nothing in this state"
              description={
                active.key === "awaiting"
                  ? "No instruction is waiting for a signature right now."
                  : undefined
              }
            />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-ground">
                <tr className="text-xs tracking-wide text-muted uppercase">
                  <th scope="col" className="px-5 py-2">
                    Reference
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Client
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Instruction
                  </th>
                  <th scope="col" className="px-3 py-2 text-right">
                    Amount
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Value date
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Signatures
                  </th>
                  <th scope="col" className="px-5 py-2">
                    Status
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id} className="border-t border-border">
                    <td className="px-5 py-2.5">
                      <Link
                        href={`/instructions/${row.id}`}
                        className="tnum font-medium text-accent underline"
                      >
                        {row.reference}
                      </Link>
                    </td>
                    <td className="px-3 py-2.5">
                      <Link href={`/clients/${row.client_id}`} className="underline">
                        {row.client_id}
                      </Link>
                    </td>
                    <td className="px-3 py-2.5">
                      {INSTRUCTION_TYPE_LABEL[row.type] ?? humanise(row.type)}
                      <p className="text-xs text-muted">{row.beneficiary}</p>
                    </td>
                    <td className="px-3 py-2.5 text-right">
                      <Money amount={row.amount} currency={row.currency} />
                    </td>
                    <td className="px-3 py-2.5 text-muted">{formatDate(row.value_date)}</td>
                    <td className="tnum px-3 py-2.5 text-muted">
                      {(row.approvals ?? []).length} of 2
                    </td>
                    <td className="px-5 py-2.5">
                      <StatusPill state={row.status} />
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
