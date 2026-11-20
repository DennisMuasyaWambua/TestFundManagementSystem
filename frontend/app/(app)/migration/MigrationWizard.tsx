"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { BatchPreview } from "@/app/(app)/migration/BatchPreview";
import { ValidationReport } from "@/app/(app)/migration/ValidationReport";
import { DateInput, Label, Select, TextArea } from "@/components/forms/fields";
import { FileDrop } from "@/components/ui/FileDrop";
import { Stepper } from "@/components/ui/Stepper";
import { Button, Card, ErrorBanner } from "@/components/ui/primitives";
import { apiGet, apiSend, newIdempotencyKey } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import type { BatchDetail, BatchRow, ClientRow, ProfitTreatment } from "@/lib/api/schema";
import { formatDate, previousMonthEnd } from "@/lib/format";

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

/** What an already-uploaded file looks like, read off batch.source_files[kind]. */
function existingFile(
  batch: BatchRow | null,
  kind: string,
): { filename: string; rows: number } | null {
  const entry = batch?.source_files?.[kind];
  if (!entry || typeof entry !== "object") return null;
  const record = entry as Record<string, unknown>;
  if (typeof record.filename !== "string") return null;
  return { filename: record.filename, rows: typeof record.rows === "number" ? record.rows : 0 };
}

/**
 * Loading a client's opening balances, in five steps.
 *
 * Nothing touches the ledger until a second person approves: the CSVs are staged,
 * validated, previewed and submitted here, and the posting happens on the approval
 * screen. That separation is the whole point -- a go-live migration is the one entry
 * nobody gets to make alone.
 *
 * `resume` picks this up mid-flow, for a batch that was already created (and maybe
 * already has files, or has already been validated) -- the mandate step is skipped
 * since the client and cutover date are fixed once the batch exists, and the wizard
 * opens on whichever step the batch's own state says comes next.
 */
export function MigrationWizard({
  clients = [],
  resume,
}: {
  clients?: ClientRow[];
  resume?: { batch: BatchRow; detail: BatchDetail };
}) {
  const router = useRouter();
  const [step, setStep] = useState<Step>(() => {
    if (!resume) return 1;
    return resume.detail.validation ? 3 : 2;
  });
  const [batch, setBatch] = useState<BatchRow | null>(resume?.batch ?? null);
  const [detail, setDetail] = useState<BatchDetail | null>(resume?.detail ?? null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [clientId, setClientId] = useState(clients[0]?.id ?? "");
  const [cutover, setCutover] = useState(previousMonthEnd());
  const [treatment, setTreatment] = useState<ProfitTreatment>("CLIENT_PROFIT_ONLY");
  const [proRata, setProRata] = useState(false);
  const [files, setFiles] = useState<Record<string, File | null>>({});
  const [acknowledgement, setAcknowledgement] = useState("");

  const [editingCutover, setEditingCutover] = useState(false);
  const [cutoverEdit, setCutoverEdit] = useState("");

  const warnings = detail?.validation?.warnings ?? [];
  const errors = detail?.validation?.errors ?? [];
  const needsAcknowledgement = warnings.length > 0 && !batch?.warnings_acknowledged_by;

  /**
   * Back to a clean slate. A batch already created server-side is simply abandoned
   * as a draft -- this test system allows any number of batches per client, so
   * there's nothing to clean up before starting another. Resuming an existing batch
   * has no "step 1" to reset to, so this leaves for a genuinely new one instead.
   */
  function startOver() {
    if (resume) {
      router.push("/migration/new");
      return;
    }
    setStep(1);
    setBatch(null);
    setDetail(null);
    setFiles({});
    setAcknowledgement("");
    setError(null);
  }

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

  /**
   * The cutover date is checked against every custodian row and the preview's
   * accrual maths, so changing it drops the batch back to DRAFT server-side --
   * whatever was already validated no longer means anything against the new date.
   */
  async function saveCutoverDate() {
    if (!batch || !cutoverEdit) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await apiSend<BatchRow>(`/opening-balances/${batch.id}/cutover-date`, {
        method: "PUT",
        body: { cutover_date: cutoverEdit },
      });
      setBatch(updated);
      setEditingCutover(false);
      if (detail) await refresh();
      if (step > 2) setStep(2);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  async function uploadAll() {
    if (!batch) return;
    const missing = FILE_KINDS.filter(
      (entry) => entry.required && !files[entry.kind] && !existingFile(batch, entry.kind),
    );
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

  // Resuming a submitted or rejected batch re-validates it immediately, so its
  // status is already back to draft/validated by the time the person sees the
  // step-3 screen -- otherwise "Submit for approval" would fail outright, since
  // the API only accepts a submit from a freshly validated batch.
  useEffect(() => {
    if (!resume) return;
    if (resume.batch.status !== "SUBMITTED" && resume.batch.status !== "REJECTED") return;
    const batchId = resume.batch.id;
    void (async () => {
      setBusy(true);
      setError(null);
      try {
        await apiSend(`/opening-balances/${batchId}/validate`, { method: "POST", body: {} });
        const fresh = await apiGet<BatchDetail>(`/opening-balances/${batchId}`);
        setDetail(fresh);
        setBatch(fresh.batch);
      } catch (caught) {
        setError(errorMessage(caught));
      } finally {
        setBusy(false);
      }
    })();
  }, [resume]);

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
      <Card
        actions={
          step > 1 ? (
            <Button variant="secondary" type="button" onClick={startOver} className="px-3 py-1.5">
              Start a new batch
            </Button>
          ) : null
        }
      >
        <Stepper steps={steps} />
      </Card>

      {batch && (
        <Card bodyClassName="px-5 py-3">
          <p className="text-sm text-muted">
            {resume && <span className="font-medium text-ink">Resuming batch #{batch.id}. </span>}
            <span className="font-medium text-ink">{batch.client_id}</span>, cutover{" "}
            {editingCutover ? (
              <span className="inline-flex items-center gap-2">
                <DateInput
                  value={cutoverEdit}
                  onChange={(event) => setCutoverEdit(event.target.value)}
                  className="mt-0 inline-block w-auto py-1"
                />
                <Button
                  type="button"
                  onClick={saveCutoverDate}
                  disabled={busy || !cutoverEdit}
                  className="px-2 py-1 text-xs"
                >
                  Save
                </Button>
                <Button
                  variant="secondary"
                  type="button"
                  onClick={() => setEditingCutover(false)}
                  disabled={busy}
                  className="px-2 py-1 text-xs"
                >
                  Cancel
                </Button>
              </span>
            ) : (
              <>
                {formatDate(batch.cutover_date)}
                {batch.status !== "POSTED" && (
                  <button
                    type="button"
                    onClick={() => {
                      setCutoverEdit(batch.cutover_date);
                      setEditingCutover(true);
                    }}
                    className="ml-2 text-xs text-accent underline"
                  >
                    Edit
                  </button>
                )}
              </>
            )}
            .
            {batch.status !== "POSTED" && (
              <>
                {" "}
                Changing it drops the batch back to draft -- any uploaded files are
                checked against the new date, so re-validate afterwards.
              </>
            )}
            {resume && (batch.status === "SUBMITTED" || batch.status === "REJECTED") && (
              <>
                {" "}
                It was {batch.status.toLowerCase()}; replacing a file or re-validating takes
                it back out of that state, and a different person will need to approve it
                again afterwards.
              </>
            )}
          </p>
        </Card>
      )}

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
                existing={existingFile(batch, entry.kind)}
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
