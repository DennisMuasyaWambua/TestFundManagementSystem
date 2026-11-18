"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Button, Card, ErrorBanner } from "@/components/ui/primitives";
import { apiSend, newIdempotencyKey } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import type { BatchRow, PreviewBody } from "@/lib/api/schema";
import { formatMoney } from "@/lib/money";

/**
 * Approving or rejecting a staged migration.
 *
 * Approval is the moment the opening entry is posted, the holdings are created, the
 * custodian figures are reconciled and the period is locked -- all in one
 * transaction. The approver cannot be the preparer, and the API enforces that, so
 * this screen states it plainly rather than trying to hide the buttons.
 */
export function BatchDecision({
  batch,
  preview,
  isPreparer,
}: {
  batch: BatchRow;
  preview: PreviewBody | null;
  isPreparer: boolean;
}) {
  const router = useRouter();
  const [dialog, setDialog] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (batch.status !== "SUBMITTED") return null;

  if (isPreparer) {
    return (
      <Card title="Waiting for someone else to approve">
        <p className="text-sm text-muted">
          You prepared this batch, so you cannot approve it. A finance head or an
          authorised signatory has to review and approve it before anything is posted.
        </p>
      </Card>
    );
  }

  const summary = (
    <dl className="space-y-1">
      <Row label="Client" value={batch.client_id} />
      <Row label="Cutover date" value={batch.cutover_date} />
      <Row label="Prepared by" value={batch.prepared_by} />
      {preview && (
        <>
          <Row label="Total debits" value={formatMoney(preview.total_debit)} />
          <Row label="Total credits" value={formatMoney(preview.total_credit)} />
          <Row label="Owed to the client (A)" value={formatMoney(preview.section_a)} />
          <Row label="Net holdings (B)" value={formatMoney(preview.section_b)} />
        </>
      )}
    </dl>
  );

  return (
    <Card title="Your decision">
      {error && <ErrorBanner message={error} />}

      <p className="mb-4 text-sm text-muted">
        Approving posts the opening entry dated {batch.cutover_date}, creates the
        holdings, records the custodian&rsquo;s figures, runs the reconciliation and locks
        the period through that date. After that it can only be undone by a reversal
        batch, approved the same way.
      </p>

      <div className="flex flex-wrap gap-2">
        <Button type="button" onClick={() => setDialog("approve")}>
          Approve and post
        </Button>
        <Button variant="danger" type="button" onClick={() => setDialog("reject")}>
          Reject
        </Button>
      </div>

      <ConfirmDialog
        open={dialog === "approve"}
        title="Approve and post these opening balances"
        confirmLabel="Approve and post"
        summary={
          <>
            <p className="mb-2 font-medium">
              This posts to the ledger and locks the period. It is not reversible by
              editing.
            </p>
            {summary}
            {preview && !preview.reconciles && (
              <p className="mt-2 text-xs text-warning-ink">
                A does not equal B: {formatMoney(preview.suspense)} will sit on suspense
                and this client&rsquo;s statements will be held until it is cleared.
              </p>
            )}
          </>
        }
        onConfirm={async () => {
          setError(null);
          try {
            await apiSend(`/opening-balances/${batch.id}/approve`, {
              method: "POST",
              idempotencyKey: newIdempotencyKey(),
              body: {},
            });
            router.refresh();
          } catch (caught) {
            setError(errorMessage(caught));
            throw caught;
          }
        }}
        onClose={() => setDialog(null)}
      />

      <ConfirmDialog
        open={dialog === "reject"}
        title="Reject this batch"
        variant="danger"
        requireReason
        reasonLabel="Why are you rejecting it?"
        reasonHint="Shown to the preparer and written to the audit log."
        summary={summary}
        confirmLabel="Reject"
        onConfirm={async (reason) => {
          setError(null);
          try {
            await apiSend(`/opening-balances/${batch.id}/reject`, {
              method: "POST",
              body: { reason },
            });
            router.refresh();
          } catch (caught) {
            setError(errorMessage(caught));
            throw caught;
          }
        }}
        onClose={() => setDialog(null)}
      />
    </Card>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="text-muted">{label}</dt>
      <dd className="text-right font-medium">{value}</dd>
    </div>
  );
}
