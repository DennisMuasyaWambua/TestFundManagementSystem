"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Button, ErrorBanner } from "@/components/ui/primitives";
import { apiSend } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import type { BatchRow } from "@/lib/api/schema";
import { formatDate } from "@/lib/format";

/**
 * Throwing away a batch that never reached the ledger.
 *
 * Nothing before POSTED has touched the ledger -- it is just staged CSV rows --
 * so deleting it is safe and, unlike every other decision here, needs no second
 * person: the same preparer who can edit a draft can discard it.
 */
export function DeleteBatch({ batch }: { batch: BatchRow }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (batch.status === "POSTED") return null;

  return (
    <>
      {error && <ErrorBanner message={error} />}
      <Button variant="danger" type="button" onClick={() => setOpen(true)}>
        Delete batch
      </Button>

      <ConfirmDialog
        open={open}
        title="Delete this batch"
        variant="danger"
        confirmLabel="Delete it"
        summary={
          <>
            <p className="mb-2 font-medium">
              This removes batch #{batch.id} and every row staged under it. It has
              not posted anything, so nothing on the ledger is affected -- but the
              uploaded files and this record are gone for good.
            </p>
            <dl className="space-y-1">
              <div className="flex justify-between gap-4">
                <dt className="text-muted">Client</dt>
                <dd className="text-right font-medium">{batch.client_id}</dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-muted">Cutover date</dt>
                <dd className="text-right font-medium">{formatDate(batch.cutover_date)}</dd>
              </div>
            </dl>
          </>
        }
        onConfirm={async () => {
          setError(null);
          try {
            await apiSend(`/opening-balances/${batch.id}`, { method: "DELETE" });
            router.push("/migration");
          } catch (caught) {
            setError(errorMessage(caught));
            throw caught;
          }
        }}
        onClose={() => setOpen(false)}
      />
    </>
  );
}
