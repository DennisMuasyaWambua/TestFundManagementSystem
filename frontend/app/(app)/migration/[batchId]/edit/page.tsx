import type { Metadata } from "next";

import { MigrationWizard } from "@/app/(app)/migration/MigrationWizard";
import { Banner, ButtonLink, PageHeader } from "@/components/ui/primitives";
import { apiFetch } from "@/lib/api/server";
import type { BatchDetail } from "@/lib/api/schema";
import { requireUser } from "@/lib/auth/me";

export const metadata: Metadata = { title: "Continue an opening balance batch" };

/**
 * Resuming a batch that was left mid-wizard -- uploading files, acknowledging a
 * warning, re-validating after a correction, or picking a submitted or rejected
 * batch back up. Reachable for anything short of POSTED: the same boundary the
 * API itself enforces (see _editable() in opening_balances.py). Re-validating a
 * submitted or rejected batch is what actually reopens it -- the API's own
 * validate() always sets the status from the outcome alone, taking it straight
 * back to draft or validated.
 */
export default async function EditBatchPage({
  params,
}: {
  params: Promise<{ batchId: string }>;
}) {
  const { batchId } = await params;
  await requireUser();
  const detail = await apiFetch<BatchDetail>(`/opening-balances/${batchId}`);
  const batch = detail.batch;

  if (batch.status === "POSTED") {
    return (
      <div className="space-y-6">
        <PageHeader title={`Opening balances · batch #${batch.id}`} />
        <Banner tone="warning" title="This batch can no longer be edited">
          It is posted to the ledger, and a posted batch can only be undone by a
          reversal batch.
        </Banner>
        <ButtonLink href={`/migration/${batch.id}`}>Back to the batch</ButtonLink>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title={`Continue batch #${batch.id}`}
        description={`${batch.client_id}, picking up from where it was left.`}
      />

      <MigrationWizard resume={{ batch, detail }} />
    </div>
  );
}
