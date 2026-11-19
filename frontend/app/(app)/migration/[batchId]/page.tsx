import type { Metadata } from "next";
import Link from "next/link";

import { BatchPreview } from "@/app/(app)/migration/BatchPreview";
import { ValidationReport } from "@/app/(app)/migration/ValidationReport";
import { BatchDecision } from "@/app/(app)/migration/[batchId]/BatchDecision";
import { StatusPill } from "@/components/ui/StatusPill";
import {
  Banner,
  ButtonLink,
  Card,
  Field,
  FieldList,
  PageHeader,
} from "@/components/ui/primitives";
import { apiFetch } from "@/lib/api/server";
import type { BatchDetail } from "@/lib/api/schema";
import { requireUser } from "@/lib/auth/me";
import { formatDate } from "@/lib/format";

export const metadata: Metadata = { title: "Opening balance batch" };

export default async function BatchPage({
  params,
}: {
  params: Promise<{ batchId: string }>;
}) {
  const { batchId } = await params;
  await requireUser();
  const detail = await apiFetch<BatchDetail>(`/opening-balances/${batchId}`);
  const batch = detail.batch;

  const files = (batch.source_files ?? {}) as Record<string, unknown>;

  return (
    <div className="space-y-6">
      <PageHeader
        title={`Opening balances · batch #${batch.id}`}
        description={`${batch.client_id} as at close of business ${formatDate(batch.cutover_date)}`}
        actions={
          <>
            <StatusPill state={batch.status} />
            <ButtonLink href="/migration">All batches</ButtonLink>
            <ButtonLink href="/migration/new" variant="primary">
              New batch
            </ButtonLink>
          </>
        }
      />

      {batch.status === "POSTED" && (
        <Banner tone="success" title="Posted to the ledger">
          Entry{" "}
          {batch.journal_entry_id && (
            <Link href={`/journal?entry=${batch.journal_entry_id}`} className="font-medium underline">
              #{batch.journal_entry_id}
            </Link>
          )}{" "}
          is dated {formatDate(batch.cutover_date)}.{" "}
          <Link
            href={`/clients/${batch.client_id}/statement?to=${batch.cutover_date}`}
            className="font-medium underline"
          >
            Open the client statement
          </Link>
          .
        </Banner>
      )}

      {batch.status === "REJECTED" && (
        <Banner tone="danger" title="Rejected">
          {batch.rejection_reason ?? "No reason was recorded."}
        </Banner>
      )}

      <Card title="The batch">
        <FieldList cols={3}>
          <Field label="Client">
            <Link href={`/clients/${batch.client_id}`} className="text-accent underline">
              {batch.client_id}
            </Link>
          </Field>
          <Field label="Cutover date">{formatDate(batch.cutover_date)}</Field>
          <Field label="Status">
            <StatusPill state={batch.status} />
          </Field>
          <Field label="Current-year profit treatment">
            {batch.profit_treatment === "CLIENT_PROFIT_ONLY"
              ? "Loaded on the client profit account only"
              : "Year-to-date income and expense included"}
          </Field>
          <Field label="Accrued profit split">
            {batch.pro_rata_accrual_split ? (
              <span className="text-warning-ink">pro rata placeholder</span>
            ) : (
              "per holding, as supplied"
            )}
          </Field>
          <Field label="Prepared by">{batch.prepared_by}</Field>
          <Field label="Approved by">{batch.approved_by ?? "not yet approved"}</Field>
          <Field label="Warnings acknowledged by">
            {batch.warnings_acknowledged_by ?? "—"}
          </Field>
          <Field label="Posted entry">
            {batch.journal_entry_id ? `#${batch.journal_entry_id}` : "—"}
          </Field>
        </FieldList>

        {Object.keys(files).length > 0 && (
          <div className="mt-4 border-t border-border pt-4">
            <h3 className="text-xs font-semibold tracking-wide text-muted uppercase">
              Source files
            </h3>
            <dl className="mt-2 space-y-1 text-sm">
              {Object.entries(files).map(([kind, value]) => (
                <div key={kind} className="flex justify-between gap-3">
                  <dt className="text-muted">{kind}</dt>
                  <dd className="truncate font-mono text-xs">{String(value)}</dd>
                </div>
              ))}
            </dl>
          </div>
        )}
      </Card>

      {detail.validation && (
        <ValidationReport
          errors={detail.validation.errors ?? []}
          warnings={detail.validation.warnings ?? []}
          acknowledgedBy={batch.warnings_acknowledged_by}
          acknowledgementNote={batch.warnings_acknowledged_note}
        />
      )}

      {detail.preview && <BatchPreview preview={detail.preview} />}

      <BatchDecision batch={batch} preview={detail.preview ?? null} />
    </div>
  );
}
