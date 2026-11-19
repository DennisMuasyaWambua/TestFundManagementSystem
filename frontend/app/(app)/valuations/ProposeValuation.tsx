"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { DateInput, FormRow, Label, MoneyInput, TextInput } from "@/components/forms/fields";
import { Button, Card, ErrorBanner } from "@/components/ui/primitives";
import { apiSend, newIdempotencyKey } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import type { AssetClass } from "@/lib/api/schema";

/**
 * Proposing a valuation.
 *
 * A Sukuk is quoted as a price per 100 of nominal; property is valued as an amount by
 * a named valuer against a report reference. Either way, a finance or signatory user
 * still has to approve it before the fair value adjustment is posted.
 */
export function ProposeValuation({
  holdingId,
  assetClass,
  currency,
}: {
  holdingId: string;
  assetClass: AssetClass;
  currency: string;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const isSukuk = assetClass === "SUKUK";

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    try {
      await apiSend("/valuations", {
        method: "POST",
        idempotencyKey: newIdempotencyKey(),
        body: {
          holding_id: holdingId,
          valuation_date: String(form.get("valuation_date") ?? ""),
          source: String(form.get("source") ?? "").trim(),
          price: isSukuk ? String(form.get("price") ?? "").trim() : null,
          value: isSukuk ? null : String(form.get("value") ?? "").trim(),
          valuer_name: isSukuk ? null : String(form.get("valuer_name") ?? "").trim() || null,
          report_ref: isSukuk ? null : String(form.get("report_ref") ?? "").trim() || null,
        },
      });
      setDone(true);
      router.refresh();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card
      title="Propose a valuation"
      description="It takes effect only once a different finance or signatory user approves it."
    >
      {done && (
        <p className="mb-4 rounded-lg bg-success-tint px-4 py-3 text-sm text-success-ink">
          Proposed. It is now waiting for approval by someone other than you.
        </p>
      )}

      <form onSubmit={submit} className="space-y-4">
        <FormRow cols={2}>
          <Label label="Valuation date" required>
            <DateInput name="valuation_date" required />
          </Label>
          {isSukuk ? (
            <Label
              label="Price per 100 of nominal"
              hint="101 means the certificate is worth 101% of its face value."
              required
            >
              <MoneyInput name="price" placeholder="101.00" required />
            </Label>
          ) : (
            <Label label={`Valuation (${currency})`} required>
              <MoneyInput name="value" required />
            </Label>
          )}
        </FormRow>

        {!isSukuk && (
          <FormRow cols={2}>
            <Label label="Valuer" hint="The independent valuer who signed the report." required>
              <TextInput name="valuer_name" required />
            </Label>
            <Label label="Report reference" required>
              <TextInput name="report_ref" required />
            </Label>
          </FormRow>
        )}

        <Label
          label="Source"
          hint={
            isSukuk
              ? "Where the price comes from, for example the exchange's closing price and its date."
              : "What the valuation is based on."
          }
          required
        >
          <TextInput name="source" required />
        </Label>

        {error && <ErrorBanner message={error} />}

        <Button type="submit" disabled={busy}>
          {busy ? "Submitting…" : "Propose it"}
        </Button>
      </form>
    </Card>
  );
}
