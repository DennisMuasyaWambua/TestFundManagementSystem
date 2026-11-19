import type { Metadata } from "next";

import { MigrationWizard } from "@/app/(app)/migration/MigrationWizard";
import { Banner, ButtonLink, PageHeader } from "@/components/ui/primitives";
import { apiFetch } from "@/lib/api/server";
import type { BatchDetail } from "@/lib/api/schema";
import { requireUser } from "@/lib/auth/me";
import { humanise } from "@/lib/format";

export const metadata: Metadata = { title: "Continue an opening balance batch" };

const EDITABLE = new Set(["DRAFT", "VALIDATED"]);

/**
 * Resuming a batch that was left mid-wizard -- uploading files, acknowledging a
 * warning, or just re-validating after a correction. Only reachable while the
 * batch is still DRAFT or VALIDATED: the same states the API itself accepts a
 * file upload or a re-validate for (see _editable() in opening_balances.py).
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

  if (!EDITABLE.has(batch.status)) {
    return (
      <div className="space-y-6">
        <PageHeader title={`Opening balances · batch #${batch.id}`} />
        <Banner tone="warning" title="This batch can no longer be edited">
          It is {humanise(batch.status).toLowerCase()}, and only a batch that is still
          draft or validated can have its files replaced or be re-validated.
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
