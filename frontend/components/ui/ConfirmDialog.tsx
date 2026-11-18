"use client";

import { type ReactNode, useEffect, useRef, useState } from "react";

import { Button, ErrorBanner } from "@/components/ui/primitives";
import { errorMessage } from "@/lib/api/errors";

/**
 * The confirmation step in front of every money-moving or destructive action.
 *
 * Two rules from the specification are enforced here rather than left to each
 * caller: the dialog restates what is about to happen (client, amount, currency,
 * account) before it can be confirmed, and a reject, cancel or reverse cannot be
 * confirmed until a reason has actually been typed -- an audit trail of empty
 * reasons is worth nothing to a regulator.
 */
export function ConfirmDialog({
  open,
  title,
  summary,
  confirmLabel,
  variant = "primary",
  requireReason = false,
  reasonLabel = "Reason",
  reasonHint,
  onConfirm,
  onClose,
}: {
  open: boolean;
  title: string;
  /** What is about to happen, restated. */
  summary: ReactNode;
  confirmLabel: string;
  variant?: "primary" | "danger";
  requireReason?: boolean;
  reasonLabel?: string;
  reasonHint?: string;
  onConfirm: (reason: string) => Promise<void> | void;
  onClose: () => void;
}) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) {
      setReason("");
      setError(null);
      setBusy(false);
      return;
    }
    dialogRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, busy, onClose]);

  if (!open) return null;

  const reasonMissing = requireReason && reason.trim().length < 3;

  async function confirm() {
    if (reasonMissing) return;
    setBusy(true);
    setError(null);
    try {
      await onConfirm(reason.trim());
      onClose();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        tabIndex={-1}
        className="w-full max-w-lg rounded-card border border-border bg-surface shadow-lg"
      >
        <div className="border-b border-border px-5 py-4">
          <h2 id="confirm-title" className="text-sm font-semibold text-ink">
            {title}
          </h2>
        </div>

        <div className="space-y-4 px-5 py-4">
          <div className="rounded-lg bg-ground px-4 py-3 text-sm text-ink">{summary}</div>

          {requireReason && (
            <label className="block">
              <span className="text-sm font-medium text-ink">{reasonLabel}</span>
              {reasonHint && <span className="mt-0.5 block text-xs text-muted">{reasonHint}</span>}
              <textarea
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                rows={3}
                required
                className="mt-1.5 w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm"
              />
              {reasonMissing && (
                <span className="mt-1 block text-xs text-muted">
                  This reason is written to the audit log, so it has to say something.
                </span>
              )}
            </label>
          )}

          {error && <ErrorBanner message={error} />}
        </div>

        <div className="flex justify-end gap-2 border-t border-border px-5 py-4">
          <Button variant="secondary" type="button" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button variant={variant} type="button" onClick={confirm} disabled={busy || reasonMissing}>
            {busy ? "Working…" : confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}
