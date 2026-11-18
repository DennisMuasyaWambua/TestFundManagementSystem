import { cn } from "@/lib/cn";
import { humanise } from "@/lib/format";

/**
 * One colour per state, plus a glyph and the word itself.
 *
 * Nothing in this system is signalled by colour alone: a signatory who cannot
 * distinguish the success green from the warning amber still reads "Settled" and
 * sees a different mark beside it.
 */
type Tone = "neutral" | "progress" | "success" | "warning" | "danger";

const TONE_CLASS: Record<Tone, string> = {
  neutral: "bg-ground text-muted ring-border",
  progress: "bg-warning-tint text-warning-ink ring-warning-ink/20",
  success: "bg-success-tint text-success-ink ring-success-ink/20",
  warning: "bg-warning-tint text-warning-ink ring-warning-ink/20",
  danger: "bg-danger-tint text-danger-ink ring-danger-ink/20",
};

const TONE_GLYPH: Record<Tone, string> = {
  neutral: "○",
  progress: "◐",
  success: "✓",
  warning: "!",
  danger: "✕",
};

/** Instruction, batch, holding and valuation states, mapped to a tone. */
const STATE_TONE: Record<string, Tone> = {
  // instructions
  PENDING_APPROVAL: "progress",
  APPROVED: "progress",
  SENT: "progress",
  SETTLED: "success",
  REJECTED: "danger",
  CANCELLED: "neutral",
  // opening balance batches
  DRAFT: "neutral",
  VALIDATED: "progress",
  SUBMITTED: "progress",
  POSTED: "success",
  // holdings
  PENDING: "progress",
  ACTIVE: "success",
  MATURED: "neutral",
  WRITTEN_OFF: "danger",
  // clients / KYC / records
  SUSPENDED: "danger",
  CLOSED: "neutral",
  // reconciliation and checklist outcomes
  MATCHED: "success",
  BREAK: "danger",
  DONE: "success",
  BLOCKED: "danger",
  TODO: "warning",
  OVERRIDDEN: "warning",
  HELD: "warning",
};

export function toneFor(state: string): Tone {
  return STATE_TONE[state] ?? "neutral";
}

export function StatusPill({
  state,
  label,
  tone,
  className,
}: {
  state: string;
  label?: string;
  tone?: Tone;
  className?: string;
}) {
  const resolved = tone ?? toneFor(state);
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium whitespace-nowrap ring-1 ring-inset",
        TONE_CLASS[resolved],
        className,
      )}
    >
      <span aria-hidden="true" className="text-[0.7rem] leading-none">
        {TONE_GLYPH[resolved]}
      </span>
      {label ?? humanise(state)}
    </span>
  );
}
