"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Button, ErrorBanner } from "@/components/ui/primitives";
import { apiSend, newIdempotencyKey } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import type { JournalEntryRow } from "@/lib/api/schema";
import { humanise } from "@/lib/format";

/**
 * Reversing a posted entry.
 *
 * This writes a mirror-image entry linked back to the original; it does not change
 * the original, which the database will not allow. A correct entry then has to be
 * posted separately, so the trail reads: what was posted, that it was reversed, why,
 * and what replaced it.
 */
export function ReverseEntry({ entry }: { entry: JournalEntryRow }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  return (
    <>
      {error && <ErrorBanner message={error} />}
      <Button variant="danger" type="button" onClick={() => setOpen(true)} className="px-3 py-1.5">
        Reverse this entry
      </Button>

      <ConfirmDialog
        open={open}
        title={`Reverse entry #${entry.id}`}
        variant="danger"
        requireReason
        reasonLabel="Why is it being reversed?"
        reasonHint="Written to the audit log and carried on the reversing entry."
        confirmLabel="Post the reversal"
        summary={
          <>
            <p className="mb-2 font-medium">
              This posts a mirror image of the entry. The original stays exactly as it
              is — the ledger is append-only.
            </p>
            <dl className="space-y-1">
              <Row label="Entry" value={`#${entry.id}`} />
              <Row label="Client" value={entry.client_id} />
              <Row label="Event" value={humanise(entry.event)} />
              <Row label="Entry date" value={entry.entry_date} />
              <Row label="Narrative" value={entry.narrative} />
            </dl>
            <p className="mt-2 text-xs text-muted">
              You will still need to post the correct entry afterwards. A reversal on
              its own leaves the books short of whatever the entry was for.
            </p>
          </>
        }
        onConfirm={async (reason) => {
          setError(null);
          try {
            await apiSend(`/journal/${entry.id}/reverse`, {
              method: "POST",
              idempotencyKey: newIdempotencyKey(),
              body: { reason },
            });
            router.refresh();
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

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="text-muted">{label}</dt>
      <dd className="text-right font-medium">{value}</dd>
    </div>
  );
}
