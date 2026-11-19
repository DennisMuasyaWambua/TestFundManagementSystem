"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { BatchPreview } from "@/app/(app)/migration/BatchPreview";
import { ValidationReport } from "@/app/(app)/migration/ValidationReport";
import { DateInput, Label, Select, TextArea } from "@/components/forms/fields";
import { FileDrop } from "@/components/ui/FileDrop";
import { Stepper } from "@/components/ui/Stepper";
import { Button, Card, ErrorBanner } from "@/components/ui/primitives";
import { apiGet, apiSend, newIdempotencyKey } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import type { BatchDetail, BatchRow, ClientRow, ProfitTreatment } from "@/lib/api/schema";
import { previousMonthEnd } from "@/lib/format";

const FILE_KINDS = [
  {
    kind: "holdings",
    label: "holdings.csv",
    hint: "One row per investment held at the cutover date.",
    required: true,
  },
  {
    kind: "lines",
    label: "lines.csv",
    hint: "The opening journal: one row per line, debit or credit.",
    required: true,
  },
  {
    kind: "custodian_balances",
    label: "custodian_balances.csv",
    hint: "The custodian's own cash balances at cutover, for the reconciliation.",
    required: true,
  },
  {
    kind: "custodian_positions",
    label: "custodian_positions.csv",
    hint: "The custodian's own position report at cutover.",
    required: true,
  },
] as const;

type Step = 1 | 2 | 3 | 4 | 5;

/**
 * Loading a client's opening balances, in five steps.
 *
 * Nothing touches the ledger until a second person approves: the CSVs are staged,
 * validated, previewed and submitted here, and the posting happens on the approval
 * screen. That separation is the whole point -- a go-live migration is the one entry
 * nobody gets to make alone.
 */
export function MigrationWizard({ clients }: { clients: ClientRow[] }) {
  const router = useRouter();
  const [step, setStep] = useState<Step>(1);
  const [batch, setBatch] = useState<BatchRow | null>(null);
  const [detail, setDetail] = useState<BatchDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [clientId, setClientId] = useState(clients[0]?.id ?? "");
  const [cutover, setCutover] = useState(previousMonthEnd());
  const [treatment, setTreatment] = useState<ProfitTreatment>("CLIENT_PROFIT_ONLY");
  const [proRata, setProRata] = useState(false);
  const [files, setFiles] = useState<Record<string, File | null>>({});
  const [acknowledgement, setAcknowledgement] = useState("");

  const warnings = detail?.validation?.warnings ?? [];
  const errors = detail?.validation?.errors ?? [];
  const needsAcknowledgement = warnings.length > 0 && !batch?.warnings_acknowledged_by;

  async function createBatch() {
    setBusy(true);
    setError(null);
    try {
      const created = await apiSend<BatchRow>("/opening-balances", {
        method: "POST",
        idempotencyKey: newIdempotencyKey(),
        body: {
          client_id: clientId,
          cutover_date: cutover,
          profit_treatment: treatment,
          pro_rata_accrual_split: proRata,
        },
      });
      setBatch(created);
      setStep(2);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  async function uploadAll() {
    if (!batch) return;
    const missing = FILE_KINDS.filter((entry) => entry.required && !files[entry.kind]);
    if (missing.length > 0) {
      setError(`Still to attach: ${missing.map((entry) => entry.label).join(", ")}.`);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      for (const entry of FILE_KINDS) {
        const file = files[entry.kind];
        if (!file) continue;
        const form = new FormData();
        form.set("kind", entry.kind);
        form.set("upload", file);
        await apiSend(`/opening-balances/${batch.id}/files`, { method: "POST", body: form });
      }
      await validate();
    } catch (caught) {
      setError(errorMessage(caught));
      setBusy(false);
    }
  }

  async function validate() {
    if (!batch) return;
    setBusy(true);
    setError(null);
    try {
      await apiSend(`/opening-balances/${batch.id}/validate`, { method: "POST", body: {} });
      await refresh();
      setStep(3);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  async function refresh(): Promise<BatchDetail | null> {
    if (!batch) return null;
    const fresh = await apiGet<BatchDetail>(`/opening-balances/${batch.id}`);
    setDetail(fresh);
    setBatch(fresh.batch);
    return fresh;
  }

  async function acknowledge() {
    if (!batch) return;
    setBusy(true);
    setError(null);
    try {
      await apiSend(`/opening-balances/${batch.id}/acknowledge-warnings`, {
        method: "POST",
        body: { note: acknowledgement },
      });
      await refresh();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    if (!batch) return;
    setBusy(true);
    setError(null);
    try {
      await apiSend(`/opening-balances/${batch.id}/submit`, { method: "POST", body: {} });
      router.push(`/migration/${batch.id}`);
    } catch (caught) {
      setError(errorMessage(caught));
      setBusy(false);
    }
  }

  const steps = [
    { label: "The mandate", state: stateFor(step, 1) },
    { label: "Upload the CSVs", state: stateFor(step, 2) },
    { label: "Validation", state: stateFor(step, 3) },
    { label: "Preview", state: stateFor(step, 4) },
    { label: "Submit for approval", state: stateFor(step, 5) },
  ];

  return (
    <div className="space-y-6">
      <Card>
        <Stepper steps={steps} />
      </Card>

      {error && <ErrorBanner message={error} />}

      {step === 1 && (
        <Card
          title="Which mandate, and as at when"
          description="These choices are stored on the batch and cannot be changed afterwards."
        >
          <div className="space-y-4">
            <Label label="Client" required>
              <Select value={clientId} onChange={(event) => setClientId(event.target.value)}>
                {clients.map((client) => (
                  <option key={client.id} value={client.id}>
                    {client.legal_name}
                  </option>
                ))}
              </Select>
            </Label>

            <Label
              label="Cutover date"
              hint="A month-end is best. Every holding loaded must still be live on this date."
              required
            >
              <DateInput value={cutover} onChange={(event) => setCutover(event.target.value)} />
            </Label>

            <Label
              label="How the current year's profit is loaded"
              hint="The default starts the new profit and loss account at zero on the cutover date."
            >
              <Select
                value={treatment}
                onChange={(event) => setTreatment(event.target.value as ProfitTreatment)}
              >
                <option value="CLIENT_PROFIT_ONLY">
                  Client profit only — three lines on the client profit account
                </option>
                <option value="INCLUDE_PL">
                  Include year-to-date income and expense, for a full-year profit and loss
                </option>
              </Select>
            </Label>

            <label className="flex items-start gap-3 rounded-lg bg-ground px-4 py-3">
              <input
                type="checkbox"
                checked={proRata}
                onChange={(event) => setProRata(event.target.checked)}
                className="mt-0.5 size-4"
              />
              <span className="text-sm">
                <span className="font-medium text-ink">
                  Split a total accrued profit figure pro rata
                </span>
                <span className="block text-muted">
                  Only if finance has supplied one total rather than a figure per deposit.
                  The split is a labelled placeholder: it raises a warning that has to be
                  acknowledged in writing, and it is listed as an open decision until the
                  custodians confirm the real breakdown.
                </span>
              </span>
            </label>

            <Button type="button" onClick={createBatch} disabled={busy || !clientId}>
              {busy ? "Creating…" : "Create the batch"}
            </Button>
          </div>
        </Card>
      )}

      {step === 2 && batch && (
        <Card
          title="Upload the four CSVs"
          description="Each file is stored with its SHA-256. The rows go to staging tables; nothing reaches the ledger."
          actions={
            <div className="flex flex-wrap gap-2">
              {FILE_KINDS.map((entry) => (
                <a
                  key={entry.kind}
                  href={`/api/v1/opening-balances/templates/${entry.kind}.csv`}
                  className="text-xs text-accent underline"
                >
                  {entry.label} template
                </a>
              ))}
            </div>
          }
        >
          <div className="space-y-5">
            {FILE_KINDS.map((entry) => (
              <FileDrop
                key={entry.kind}
                name={entry.kind}
                label={entry.label}
                hint={entry.hint}
                accept=".csv,text/csv"
                required={entry.required}
                onFileChange={(file) =>
                  setFiles((previous) => ({ ...previous, [entry.kind]: file }))
                }
              />
            ))}

            <Button type="button" onClick={uploadAll} disabled={busy}>
              {busy ? "Uploading and validating…" : "Upload and validate"}
            </Button>
          </div>
        </Card>
      )}

      {step >= 3 && detail && (
        <>
          <ValidationReport errors={errors} warnings={warnings} />

          {needsAcknowledgement && (
            <Card
              title="Acknowledge the warnings"
              description="A warning does not block the load, but someone has to put their name to it."
            >
              <div className="space-y-4">
                <Label
                  label="What you are acknowledging, and why it is acceptable"
                  hint="This is stored on the batch and shown to the approver."
                  required
                >
                  <TextArea
                    value={acknowledgement}
                    onChange={(event) => setAcknowledgement(event.target.value)}
                  />
                </Label>
                <Button
                  type="button"
                  onClick={acknowledge}
                  disabled={busy || acknowledgement.trim().length < 10}
                >
                  {busy ? "Saving…" : "Acknowledge them"}
                </Button>
              </div>
            </Card>
          )}

          {errors.length === 0 && detail.preview && (
            <>
              <BatchPreview preview={detail.preview} />
              <Card>
                <div className="flex flex-wrap items-center gap-3">
                  <Button
                    type="button"
                    onClick={submit}
                    disabled={busy || needsAcknowledgement}
                  >
                    {busy ? "Submitting…" : "Submit for approval"}
                  </Button>
                  <Button variant="secondary" type="button" onClick={validate} disabled={busy}>
                    Re-validate
                  </Button>
                  <p className="text-sm text-muted">
                    A different person — finance head or an authorised signatory — has to
                    approve this before anything is posted.
                  </p>
                </div>
              </Card>
            </>
          )}

          {errors.length > 0 && (
            <Card>
              <div className="flex flex-wrap items-center gap-3">
                <Button type="button" onClick={() => setStep(2)} variant="secondary">
                  Replace the files
                </Button>
                <Button type="button" onClick={validate} disabled={busy}>
                  {busy ? "Validating…" : "Validate again"}
                </Button>
                <p className="text-sm text-muted">
                  Correct the CSVs and re-upload. Errors must be nil before the batch can
                  be submitted.
                </p>
              </div>
            </Card>
          )}
        </>
      )}
    </div>
  );
}

function stateFor(current: Step, step: Step): "done" | "current" | "todo" {
  if (current > step) return "done";
  if (current === step) return "current";
  return "todo";
}
