"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Money } from "@/components/money/Money";
import { Checklist, ChecklistItem } from "@/components/ui/ChecklistItem";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Button, Card, ErrorBanner } from "@/components/ui/primitives";
import { apiGet, apiSend, newIdempotencyKey } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import type {
  AccrualRun,
  Checklist as ChecklistData,
  ClientRow,
  CloseResponse,
  Revaluation,
} from "@/lib/api/schema";
import { formatDate } from "@/lib/format";

/**
 * Closing a month for one client.
 *
 * The order is fixed by the specification and enforced by the API: accruals and rent
 * to the period end, then the exchange revaluation at the closing rate, then the
 * reconciliation must be clean (or overridden with a written reason), and only then
 * is the profit and loss swept to the client's profit.
 *
 * Each step can be re-run safely: the accrual posts the difference to a cumulative
 * target, so running it twice posts nothing the second time.
 */
export function CloseRunner({
  client,
  periodEnd,
  initial,
}: {
  client: ClientRow;
  periodEnd: string;
  initial: ChecklistData;
}) {
  const router = useRouter();
  const [checklist, setChecklist] = useState(initial);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [closing, setClosing] = useState(false);
  const [result, setResult] = useState<CloseResponse | null>(null);

  const clientPath = encodeURIComponent(client.id);

  async function reloadChecklist() {
    const fresh = await apiGet<ChecklistData>(
      `/clients/${clientPath}/close-checklist?period_end=${periodEnd}`,
    );
    setChecklist(fresh);
  }

  async function runAccruals() {
    setBusy("accruals");
    setError(null);
    setMessage(null);
    try {
      const run = await apiSend<AccrualRun>(
        `/clients/${clientPath}/accruals?as_of=${periodEnd}`,
        { method: "POST", idempotencyKey: newIdempotencyKey(), body: {} },
      );
      setMessage(
        run.changed
          ? `Posted profit ${run.profit_posted} and fees ${run.fee_posted}` +
              (run.rent_invoices.length > 0
                ? `, and invoiced ${run.rent_invoices.length} month(s) of rent.`
                : ".")
          : "Already up to date: nothing further to accrue.",
      );
      if (run.skipped.length > 0) {
        setMessage(
          (previous) =>
            `${previous ?? ""} Skipped: ${run.skipped.join("; ")}.`,
        );
      }
      await reloadChecklist();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(null);
    }
  }

  async function runRevaluation() {
    setBusy("fx_revaluation");
    setError(null);
    setMessage(null);
    try {
      const run = await apiSend<Revaluation>(
        `/clients/${clientPath}/fx-revaluation?as_of=${periodEnd}`,
        { method: "POST", idempotencyKey: newIdempotencyKey(), body: {} },
      );
      setMessage(
        run.changed
          ? `Revalued ${run.lines.length} balance(s); net exchange movement ${run.net}.`
          : "No foreign-currency balance needed restating.",
      );
      await reloadChecklist();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(null);
    }
  }

  const blocking = checklist.items.filter((item) => !item.done && item.blocking);

  const ACTION: Record<string, (() => void) | undefined> = {
    accruals: runAccruals,
    fx_revaluation: runRevaluation,
  };

  return (
    <Card
      title={client.legal_name}
      description={`Closing ${formatDate(periodEnd)}`}
      actions={
        result ? (
          <span className="text-sm text-success-ink">
            Closed through {formatDate(result.locked_through)}
          </span>
        ) : null
      }
    >
      {error && (
        <div className="mb-4">
          <ErrorBanner message={error} />
        </div>
      )}

      {message && (
        <p className="mb-4 rounded-lg bg-ground px-4 py-3 text-sm text-ink">{message}</p>
      )}

      {result && (
        <p className="mb-4 rounded-lg bg-success-tint px-4 py-3 text-sm text-success-ink">
          {result.already_closed
            ? "This period was already closed."
            : "Closed."}{" "}
          Net profit of <Money amount={result.net_profit} /> was moved to the
          client&rsquo;s profit account for the period through{" "}
          {formatDate(result.locked_through)}.
        </p>
      )}

      <Checklist>
        {checklist.items.map((item) => {
          const run = ACTION[item.key];
          return (
            <ChecklistItem
              key={item.key}
              label={item.label}
              state={item.done ? "DONE" : item.blocking ? "BLOCKED" : "TODO"}
              detail={item.detail}
              action={
                run && !item.done ? (
                  <Button
                    variant="secondary"
                    type="button"
                    onClick={run}
                    disabled={busy !== null}
                    className="px-3 py-1.5"
                  >
                    {busy === item.key ? "Running…" : "Run it"}
                  </Button>
                ) : null
              }
            />
          );
        })}
      </Checklist>

      <div className="mt-5 flex flex-wrap items-center gap-3 border-t border-border pt-4">
        <Button
          type="button"
          onClick={() => setClosing(true)}
          disabled={busy !== null || result !== null}
        >
          Close the period
        </Button>
        {!checklist.can_close && blocking.length > 0 && (
          <p className="text-sm text-warning-ink">
            {blocking.length} item{blocking.length === 1 ? "" : "s"} still blocking. A
            reconciliation break can be overridden with a written reason; the rest must
            be done.
          </p>
        )}
      </div>

      <ConfirmDialog
        open={closing}
        title={`Close ${formatDate(periodEnd)} for ${client.legal_name}`}
        confirmLabel="Close and lock"
        requireReason={!checklist.can_close}
        reasonLabel="Why are you closing with items outstanding?"
        reasonHint="Recorded as the override reason on the audit trail."
        summary={
          <>
            <p className="mb-2 font-medium">
              This sweeps the period&rsquo;s income and costs to the client&rsquo;s profit
              and locks the period.
            </p>
            <dl className="space-y-1">
              <div className="flex justify-between gap-4">
                <dt className="text-muted">Client</dt>
                <dd className="font-medium">{client.legal_name}</dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-muted">Period end</dt>
                <dd className="font-medium">{periodEnd}</dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-muted">Outstanding blocking items</dt>
                <dd className="font-medium">{blocking.length}</dd>
              </div>
            </dl>
            <p className="mt-2 text-xs text-muted">
              This sweeps the period&rsquo;s income and costs to the client&rsquo;s profit
              for {periodEnd}.
            </p>
          </>
        }
        onConfirm={async (reason) => {
          setError(null);
          try {
            const closed = await apiSend<CloseResponse>(
              `/clients/${clientPath}/close?period_end=${periodEnd}`,
              {
                method: "POST",
                idempotencyKey: newIdempotencyKey(),
                body: reason ? { override_reason: reason } : {},
              },
            );
            setResult(closed);
            await reloadChecklist();
            router.refresh();
          } catch (caught) {
            setError(errorMessage(caught));
            throw caught;
          }
        }}
        onClose={() => setClosing(false)}
      />
    </Card>
  );
}
