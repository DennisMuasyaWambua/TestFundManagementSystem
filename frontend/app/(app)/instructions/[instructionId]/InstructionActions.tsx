"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { FileDrop } from "@/components/ui/FileDrop";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Button, ErrorBanner } from "@/components/ui/primitives";
import { DateInput, Label, MoneyInput, TextInput } from "@/components/forms/fields";
import { apiSend, newIdempotencyKey } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import type { InstructionDetail } from "@/lib/api/schema";
import { formatMoney } from "@/lib/money";

/**
 * The actions available on one instruction, by role and state.
 *
 * Every one of them restates the client, the amount and the account before it can be
 * confirmed, and the destructive ones require a typed reason. The buttons shown here
 * mirror `can_approve` / `can_dispatch` / `can_settle` as the API reports them, so
 * this screen cannot offer an action the API would refuse.
 */
export function InstructionActions({ detail }: { detail: InstructionDetail }) {
  const router = useRouter();
  const instruction = detail.instruction;
  const [dialog, setDialog] = useState<"approve" | "reject" | "cancel" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const summary = (
    <dl className="space-y-1">
      <Row label="Client" value={instruction.client_id} />
      <Row label="Custody account" value={instruction.custody_account_id} />
      <Row
        label="Amount"
        value={formatMoney(instruction.amount, { currency: instruction.currency })}
      />
      <Row label="Beneficiary" value={instruction.beneficiary} />
      <Row label="Value date" value={instruction.value_date} />
    </dl>
  );

  async function act(path: string, body?: unknown) {
    await apiSend(`/instructions/${instruction.id}/${path}`, {
      method: "POST",
      body: body ?? {},
      idempotencyKey: newIdempotencyKey(),
    });
    router.refresh();
  }

  return (
    <div className="space-y-4">
      {error && <ErrorBanner message={error} />}

      <div className="flex flex-wrap gap-2">
        {detail.can_approve && (
          <>
            <Button type="button" onClick={() => setDialog("approve")}>
              Approve and sign
            </Button>
            <Button variant="danger" type="button" onClick={() => setDialog("reject")}>
              Reject
            </Button>
          </>
        )}

        {(instruction.status === "PENDING_APPROVAL" || instruction.status === "APPROVED") && (
          <Button variant="secondary" type="button" onClick={() => setDialog("cancel")}>
            Cancel
          </Button>
        )}

        {instruction.status !== "PENDING_APPROVAL" && (
          <a
            href={`/api/v1/instructions/${instruction.id}/letter.pdf`}
            target="_blank"
            rel="noreferrer"
            className="btn inline-flex items-center rounded-lg bg-surface px-4 py-2 text-sm font-medium text-ink ring-1 ring-border ring-inset hover:bg-ground"
          >
            Download the letter
          </a>
        )}
      </div>

      {detail.can_dispatch && instruction.status === "APPROVED" && (
        <MarkSentForm instructionId={instruction.id} onDone={() => router.refresh()} />
      )}

      {detail.can_settle && instruction.status === "SENT" && (
        <SettleForm
          instruction={instruction}
          onDone={() => router.refresh()}
        />
      )}

      <ConfirmDialog
        open={dialog === "approve"}
        title="Approve this instruction"
        summary={
          <>
            <p className="mb-2 font-medium">
              You are adding your signature to a custody instruction.
            </p>
            {summary}
            <p className="mt-2 text-xs text-muted">
              Two different signatories are required, and neither may be the person who
              prepared it. Your approval is recorded against your name with the time.
            </p>
          </>
        }
        confirmLabel="Approve"
        onConfirm={async () => {
          setError(null);
          try {
            await act("approve");
          } catch (caught) {
            setError(errorMessage(caught));
            throw caught;
          }
        }}
        onClose={() => setDialog(null)}
      />

      <ConfirmDialog
        open={dialog === "reject"}
        title="Reject this instruction"
        variant="danger"
        requireReason
        reasonLabel="Why are you rejecting it?"
        reasonHint="This is written to the audit log and shown to the preparer."
        summary={summary}
        confirmLabel="Reject"
        onConfirm={async (reason) => {
          setError(null);
          try {
            await act("reject", { reason });
          } catch (caught) {
            setError(errorMessage(caught));
            throw caught;
          }
        }}
        onClose={() => setDialog(null)}
      />

      <ConfirmDialog
        open={dialog === "cancel"}
        title="Cancel this instruction"
        variant="danger"
        requireReason
        reasonLabel="Why are you cancelling it?"
        summary={summary}
        confirmLabel="Cancel the instruction"
        onConfirm={async (reason) => {
          setError(null);
          try {
            await act("cancel", { reason });
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

/** Upload the wet-signed scan and mark the letter sent to the custodian. */
function MarkSentForm({
  instructionId,
  onDone,
}: {
  instructionId: number;
  onDone: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) {
      setError("Attach the scan of the signed letter first.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      form.set("signed_copy", file);
      await apiSend(`/instructions/${instructionId}/sent`, { method: "POST", body: form });
      onDone();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      onSubmit={submit}
      className="space-y-4 rounded-lg border border-border bg-ground px-4 py-4"
    >
      <div>
        <h3 className="text-sm font-semibold text-ink">Send it to the custodian</h3>
        <p className="mt-0.5 text-sm text-muted">
          Print the letter, have both signatories sign it, then upload the scan. The
          system stores its SHA-256 so the copy sent can always be identified.
        </p>
      </div>

      <FileDrop
        name="signed_copy"
        label="Scan of the signed letter"
        accept="application/pdf,image/*"
        required
        onFileChange={setFile}
      />

      {error && <ErrorBanner message={error} />}

      <Button type="submit" disabled={busy || !file}>
        {busy ? "Uploading…" : "Mark as sent"}
      </Button>
    </form>
  );
}

/**
 * Record the custodian's confirmation, which is what posts the movement.
 *
 * The amount defaults to the instructed amount and the API refuses anything else:
 * money is booked for exactly what was instructed, or not at all.
 */
function SettleForm({
  instruction,
  onDone,
}: {
  instruction: InstructionDetail["instruction"];
  onDone: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    try {
      await apiSend(`/instructions/${instruction.id}/settle`, {
        method: "POST",
        idempotencyKey: newIdempotencyKey(),
        body: {
          confirmation_ref: String(form.get("confirmation_ref") ?? "").trim(),
          settled_on: String(form.get("settled_on") ?? ""),
          amount: String(form.get("amount") ?? "").trim(),
        },
      });
      onDone();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      onSubmit={submit}
      className="space-y-4 rounded-lg border border-border bg-ground px-4 py-4"
    >
      <div>
        <h3 className="text-sm font-semibold text-ink">Record the custodian&rsquo;s confirmation</h3>
        <p className="mt-0.5 text-sm text-muted">
          The movement is booked to the ledger only now, and only for the amount that
          was instructed.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Label label="Custodian confirmation reference" required>
          <TextInput name="confirmation_ref" required autoComplete="off" />
        </Label>
        <Label label="Settled on" required>
          <DateInput name="settled_on" defaultValue={instruction.value_date} required />
        </Label>
        <Label label={`Amount (${instruction.currency})`} required>
          <MoneyInput name="amount" defaultValue={instruction.amount} required />
        </Label>
      </div>

      {error && <ErrorBanner message={error} />}

      <Button type="submit" disabled={busy}>
        {busy ? "Booking…" : "Record settlement"}
      </Button>
    </form>
  );
}
