"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { DateInput, FormRow, Label, RateInput, TextInput } from "@/components/forms/fields";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Button, Card, ErrorBanner } from "@/components/ui/primitives";
import { apiSend } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";

/**
 * Onboarding a client, step one: the mandate record itself.
 *
 * KYC (compliance) and the first custody account (finance) still have to follow
 * before an instruction can be raised for this client -- the banner on the next
 * screen names exactly what's missing.
 */
export function NewClientForm() {
  const router = useRouter();
  const [id, setId] = useState("");
  const [legalName, setLegalName] = useState("");
  const [baseCurrency, setBaseCurrency] = useState("USD");
  const [agreementRef, setAgreementRef] = useState("");
  const [agreementDate, setAgreementDate] = useState("");
  const [finalWhtRate, setFinalWhtRate] = useState("0");
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const ready = Boolean(
    id.trim().length >= 2 && legalName.trim() && baseCurrency.trim().length === 3,
  );

  return (
    <Card
      title="The mandate"
      description="A short, stable id (it appears on every holding and instruction for this client) and its legal name and reporting currency."
    >
      <div className="space-y-4">
        <FormRow cols={3}>
          <Label
            label="Client id"
            required
            hint="Letters, digits and hyphens only; cannot be changed later."
          >
            <TextInput
              value={id}
              onChange={(event) => setId(event.target.value.toUpperCase())}
              placeholder="e.g. RAYAN"
            />
          </Label>
          <Label label="Legal name" required className="sm:col-span-2">
            <TextInput
              value={legalName}
              onChange={(event) => setLegalName(event.target.value)}
              placeholder="e.g. Rayan Realstate Development Sarl"
            />
          </Label>
        </FormRow>

        <FormRow cols={3}>
          <Label label="Base (reporting) currency" required hint="ISO 4217, e.g. USD">
            <TextInput
              value={baseCurrency}
              maxLength={3}
              onChange={(event) => setBaseCurrency(event.target.value.toUpperCase())}
            />
          </Label>
          <Label label="Agreement reference" hint="The signed IMA reference, if known yet.">
            <TextInput
              value={agreementRef}
              onChange={(event) => setAgreementRef(event.target.value)}
            />
          </Label>
          <Label label="Agreement date">
            <DateInput
              value={agreementDate}
              onChange={(event) => setAgreementDate(event.target.value)}
            />
          </Label>
        </FormRow>

        <Label
          label="Final withholding tax rate"
          hint="As a decimal, e.g. 0.05 for 5%. 0 until the tax adviser confirms otherwise."
          className="max-w-xs"
        >
          <RateInput
            value={finalWhtRate}
            onChange={(event) => setFinalWhtRate(event.target.value)}
          />
        </Label>

        {error && <ErrorBanner message={error} />}

        <div className="rounded-lg bg-ground px-4 py-3 text-sm text-muted">
          No instruction can be raised for this client until compliance approves KYC
          and finance adds a custody account — both on the client&rsquo;s own page,
          once it exists.
        </div>

        <Button type="button" disabled={!ready} onClick={() => setConfirming(true)}>
          Create the client
        </Button>
      </div>

      <ConfirmDialog
        open={confirming}
        title="Create this client"
        confirmLabel="Create it"
        summary={
          <dl className="space-y-1">
            <Row label="Client id" value={id} />
            <Row label="Legal name" value={legalName} />
            <Row label="Base currency" value={baseCurrency} />
            {agreementRef && <Row label="Agreement reference" value={agreementRef} />}
          </dl>
        }
        onConfirm={async () => {
          setError(null);
          try {
            await apiSend("/clients", {
              method: "POST",
              body: {
                id,
                legal_name: legalName,
                base_currency: baseCurrency,
                agreement_ref: agreementRef || null,
                agreement_date: agreementDate || null,
                final_wht_rate: finalWhtRate || "0",
              },
            });
            router.push(`/clients/${encodeURIComponent(id)}`);
          } catch (caught) {
            setError(errorMessage(caught));
            throw caught;
          }
        }}
        onClose={() => setConfirming(false)}
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
