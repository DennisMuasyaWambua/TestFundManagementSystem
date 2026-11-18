"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { DateInput, FormRow, Label, RateInput, TextInput } from "@/components/forms/fields";
import { Button, Card, ErrorBanner } from "@/components/ui/primitives";
import { apiSend, newIdempotencyKey } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";

/**
 * Entering a daily rate.
 *
 * The rate is read as "how many units of the base currency one unit of this currency
 * buys", which is the direction every posting uses. A missing rate for a posting date
 * is a hard error in the ledger, not a silent 1.0, so this screen is how the ledger
 * stays postable.
 */
export function FxRateForm({ defaultDate }: { defaultDate: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      await apiSend("/fx-rates", {
        method: "POST",
        idempotencyKey: newIdempotencyKey(),
        body: {
          currency: String(form.get("currency") ?? "").trim().toUpperCase(),
          base_currency: String(form.get("base_currency") ?? "").trim().toUpperCase(),
          rate_date: String(form.get("rate_date") ?? ""),
          rate: String(form.get("rate") ?? "").trim(),
          source: String(form.get("source") ?? "").trim() || undefined,
        },
      });
      setSaved(true);
      router.refresh();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card
      title="Enter a rate"
      description="One unit of the currency, expressed in units of the base currency."
    >
      <form onSubmit={submit} className="space-y-4">
        <FormRow cols={3}>
          <Label label="Currency" hint="For example KES." required>
            <TextInput
              name="currency"
              maxLength={3}
              required
              className="uppercase"
              placeholder="KES"
            />
          </Label>
          <Label label="Against base currency" required>
            <TextInput
              name="base_currency"
              maxLength={3}
              defaultValue="USD"
              required
              className="uppercase"
            />
          </Label>
          <Label label="Rate date" required>
            <DateInput name="rate_date" defaultValue={defaultDate} required />
          </Label>
        </FormRow>

        <FormRow cols={2}>
          <Label
            label="Rate"
            hint="Eight decimal places. 0.00780000 means one KES buys 0.0078 USD."
            required
          >
            <RateInput name="rate" required placeholder="0.00780000" />
          </Label>
          <Label label="Source" hint="For example the CBK indicative mean rate.">
            <TextInput name="source" defaultValue="CBK indicative mean" />
          </Label>
        </FormRow>

        {error && <ErrorBanner message={error} />}
        {saved && (
          <p className="rounded-lg bg-success-tint px-4 py-3 text-sm text-success-ink">
            Rate saved.
          </p>
        )}

        <Button type="submit" disabled={busy}>
          {busy ? "Saving…" : "Save the rate"}
        </Button>
      </form>
    </Card>
  );
}
