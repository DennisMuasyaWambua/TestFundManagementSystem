"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Button, ErrorBanner } from "@/components/ui/primitives";
import { apiSend, newIdempotencyKey } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import type { ValuationRow } from "@/lib/api/schema";
import { formatMoney } from "@/lib/money";

/**
 * Approving or rejecting a proposed valuation.
 *
 * Approval is what posts the fair value adjustment -- cost is never overwritten, so
 * the original amount paid stays visible alongside the adjustment.
 */
export function ValuationDecision({ valuation }: { valuation: ValuationRow }) {
  const router = useRouter();
  const [dialog, setDialog] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (valuation.status !== "PENDING") return null;

  const summary = (
    <dl className="space-y-1">
      <Row label="Deal" value={valuation.holding_id} />
      <Row label="Client" value={valuation.client_id} />
      <Row label="Valuation date" value={valuation.valuation_date} />
      <Row label="Value" value={formatMoney(valuation.value)} />
      {valuation.price && <Row label="Price per 100 nominal" value={valuation.price} />}
      <Row label="Source" value={valuation.source} />
      {valuation.valuer_name && <Row label="Valuer" value={valuation.valuer_name} />}
    </dl>
  );

  return (
    <div className="space-y-2">
      {error && <ErrorBanner message={error} />}

      <div className="flex gap-2">
        <Button type="button" onClick={() => setDialog("approve")} className="px-3 py-1.5">
          Approve
        </Button>
        <Button
          variant="danger"
          type="button"
          onClick={() => setDialog("reject")}
          className="px-3 py-1.5"
        >
          Reject
        </Button>
      </div>

      <ConfirmDialog
        open={dialog === "approve"}
        title="Approve this valuation"
        confirmLabel="Approve and post"
        summary={
          <>
            <p className="mb-2 font-medium">
              Approving posts the fair value adjustment so that cost plus adjustment
              equals this value. The cost itself is not changed.
            </p>
            {summary}
          </>
        }
        onConfirm={async () => {
          setError(null);
          try {
            await apiSend(`/valuations/${valuation.id}/approve`, {
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
        title="Reject this valuation"
        variant="danger"
        requireReason
        reasonLabel="Why are you rejecting it?"
        summary={summary}
        confirmLabel="Reject"
        onConfirm={async (reason) => {
          setError(null);
          try {
            await apiSend(`/valuations/${valuation.id}/reject`, {
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
    </div>
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
