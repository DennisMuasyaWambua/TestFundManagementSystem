"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { DateInput, FormRow, Label, MoneyInput, TextInput } from "@/components/forms/fields";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Button, Card, ErrorBanner } from "@/components/ui/primitives";
import { apiSend, newIdempotencyKey } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import type { HoldingDetail } from "@/lib/api/schema";

type Action =
  | "profit"
  | "principal"
  | "maturity"
  | "rent"
  | "tenant-deposit"
  | "write-off";

const TITLES: Record<Action, string> = {
  profit: "Record profit received",
  principal: "Record a principal repayment",
  maturity: "Record the maturity",
  rent: "Record rent received",
  "tenant-deposit": "Record a tenant deposit",
  "write-off": "Write this financing off",
};

/**
 * Money in, against one holding.
 *
 * No letter is needed for money coming in -- the custodian has already credited the
 * account -- but the custodian's advice reference is mandatory on every one of these,
 * so each posting can be traced back to the document that evidences it.
 */
export function HoldingReceipts({
  detail,
  canRecord,
  canOperate,
}: {
  detail: HoldingDetail;
  canRecord: boolean;
  canOperate: boolean;
}) {
  const router = useRouter();
  const holding = detail.holding;
  const [open, setOpen] = useState<Action | null>(null);
  const [error, setError] = useState<string | null>(null);

  const isProperty = holding.asset_class === "PROPERTY";
  const isFinancing = holding.asset_class === "PRIVATE_FINANCING";
  const settled = holding.status !== "ACTIVE";

  if (!canRecord && !canOperate) return null;

  const actions: Action[] = [];
  if (canRecord && !settled) {
    if (isProperty) actions.push("rent", "tenant-deposit");
    else actions.push("profit");
    if (isFinancing) actions.push("principal");
    actions.push("maturity");
  }
  if (canOperate && isFinancing && !settled) actions.push("write-off");

  if (actions.length === 0) return null;

  return (
    <Card
      title="Record a movement"
      description="Quote the custodian's credit advice reference on everything booked here."
    >
      {error && <ErrorBanner message={error} />}

      <div className="flex flex-wrap gap-2">
        {actions.map((action) => (
          <Button
            key={action}
            type="button"
            variant={action === "write-off" ? "danger" : "secondary"}
            onClick={() => {
              setError(null);
              setOpen(action);
            }}
          >
            {TITLES[action]}
          </Button>
        ))}
      </div>

      {open && open !== "write-off" && (
        <ReceiptForm
          action={open}
          holdingId={holding.id}
          currency={holding.currency}
          detail={detail}
          onClose={() => setOpen(null)}
          onDone={() => {
            setOpen(null);
            router.refresh();
          }}
        />
      )}

      <ConfirmDialog
        open={open === "write-off"}
        title="Write this financing off"
        variant="danger"
        requireReason
        reasonLabel="Why is it being written off?"
        reasonHint="This closes the holding and charges the loss to the client's profit."
        summary={
          <dl className="space-y-1">
            <div className="flex justify-between gap-4">
              <dt className="text-muted">Deal</dt>
              <dd className="font-medium">{holding.id}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-muted">Client</dt>
              <dd className="font-medium">{holding.client_id}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-muted">Outstanding to be written off</dt>
              <dd className="font-medium">
                {holding.currency} {detail.balances.outstanding}
              </dd>
            </div>
          </dl>
        }
        confirmLabel="Write it off"
        onConfirm={async (reason) => {
          try {
            await apiSend(`/holdings/${encodeURIComponent(holding.id)}/write-off`, {
              method: "POST",
              idempotencyKey: newIdempotencyKey(),
              body: { reason, on: new Date().toISOString().slice(0, 10) },
            });
            router.refresh();
          } catch (caught) {
            setError(errorMessage(caught));
            throw caught;
          }
        }}
        onClose={() => setOpen(null)}
      />
    </Card>
  );
}

function ReceiptForm({
  action,
  holdingId,
  currency,
  detail,
  onClose,
  onDone,
}: {
  action: Exclude<Action, "write-off">;
  holdingId: string;
  currency: string;
  detail: HoldingDetail;
  onClose: () => void;
  onDone: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const common = {
      value_date: String(form.get("value_date") ?? ""),
      advice_ref: String(form.get("advice_ref") ?? "").trim(),
    };

    let body: Record<string, unknown>;
    switch (action) {
      case "profit":
      case "rent":
        body = {
          ...common,
          gross: String(form.get("gross") ?? "").trim(),
          wht: String(form.get("wht") ?? "0").trim() || "0",
        };
        break;
      case "principal":
      case "tenant-deposit":
        body = { ...common, amount: String(form.get("amount") ?? "").trim() };
        break;
      case "maturity":
        body = {
          ...common,
          principal: String(form.get("principal") ?? "").trim(),
          profit: String(form.get("profit") ?? "").trim(),
          wht: String(form.get("wht") ?? "0").trim() || "0",
        };
        break;
    }

    setBusy(true);
    setError(null);
    try {
      await apiSend(`/holdings/${encodeURIComponent(holdingId)}/${action}`, {
        method: "POST",
        idempotencyKey: newIdempotencyKey(),
        body,
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
      className="mt-4 space-y-4 rounded-lg border border-border bg-ground px-4 py-4"
    >
      <h3 className="text-sm font-semibold text-ink">{TITLES[action]}</h3>

      <FormRow cols={2}>
        <Label label="Value date" required>
          <DateInput name="value_date" required />
        </Label>
        <Label
          label="Custodian advice reference"
          hint="The credit advice this posting is evidenced by."
          required
        >
          <TextInput name="advice_ref" required autoComplete="off" />
        </Label>
      </FormRow>

      {(action === "profit" || action === "rent") && (
        <FormRow cols={2}>
          <Label
            label={`Gross amount (${currency})`}
            hint={
              action === "profit"
                ? `Accrued so far: ${detail.balances.accrued_profit}`
                : `Rent invoiced and unpaid: ${detail.balances.rent_receivable}`
            }
            required
          >
            <MoneyInput name="gross" required />
          </Label>
          <Label
            label="Withholding tax deducted at source"
            hint="What the paying bank kept. Leave as zero if none."
          >
            <MoneyInput name="wht" defaultValue="0.00" />
          </Label>
        </FormRow>
      )}

      {(action === "principal" || action === "tenant-deposit") && (
        <Label
          label={`Amount (${currency})`}
          hint={
            action === "principal"
              ? `Outstanding: ${detail.balances.outstanding}`
              : undefined
          }
          required
        >
          <MoneyInput name="amount" required />
        </Label>
      )}

      {action === "maturity" && (
        <FormRow cols={3}>
          <Label
            label={`Principal repaid (${currency})`}
            hint={`Carrying amount: ${detail.balances.outstanding}`}
            required
          >
            <MoneyInput name="principal" defaultValue={detail.balances.outstanding} required />
          </Label>
          <Label
            label="Profit paid"
            hint={`Accrued: ${detail.balances.accrued_profit}. Any difference is trued up.`}
            required
          >
            <MoneyInput name="profit" defaultValue={detail.balances.accrued_profit} required />
          </Label>
          <Label label="Withholding tax at source">
            <MoneyInput name="wht" defaultValue="0.00" />
          </Label>
        </FormRow>
      )}

      {error && <ErrorBanner message={error} />}

      <div className="flex gap-2">
        <Button type="submit" disabled={busy}>
          {busy ? "Booking…" : "Book it"}
        </Button>
        <Button variant="secondary" type="button" onClick={onClose} disabled={busy}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
