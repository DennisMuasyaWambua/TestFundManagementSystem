import { cn } from "@/lib/cn";

export type Step = {
  label: string;
  /** done: behind us. current: where we are. todo: ahead. failed: ended here. */
  state: "done" | "current" | "todo" | "failed";
  detail?: string;
};

/**
 * Progress through a lifecycle -- an instruction's five steps, or a migration
 * wizard's.  The state is spelled out in text for each step as well as shown by
 * colour, so the stage is never signalled by colour alone.
 */
export function Stepper({ steps }: { steps: Step[] }) {
  return (
    <ol className="flex flex-col gap-3 sm:flex-row sm:items-start sm:gap-0">
      {steps.map((step, index) => {
        const last = index === steps.length - 1;
        return (
          <li key={step.label} className="flex flex-1 items-start gap-3 sm:flex-col sm:gap-2">
            <div className="flex items-center gap-3 sm:w-full">
              <span
                aria-hidden="true"
                className={cn(
                  "flex size-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold",
                  step.state === "done" && "bg-success-tint text-success-ink",
                  step.state === "current" && "bg-accent text-accent-ink",
                  step.state === "todo" && "bg-ground text-muted ring-1 ring-border ring-inset",
                  step.state === "failed" && "bg-danger-tint text-danger-ink",
                )}
              >
                {step.state === "done" ? "✓" : step.state === "failed" ? "✕" : index + 1}
              </span>
              {!last && (
                <span
                  aria-hidden="true"
                  className={cn(
                    "hidden h-0.5 flex-1 sm:block",
                    step.state === "done" ? "bg-success-ink/30" : "bg-border",
                  )}
                />
              )}
            </div>
            <div className="min-w-0 sm:pr-4">
              <p
                className={cn(
                  "text-sm",
                  step.state === "current" ? "font-semibold text-ink" : "text-muted",
                )}
              >
                {step.label}
              </p>
              <p className="sr-only">
                {step.state === "done"
                  ? "completed"
                  : step.state === "current"
                    ? "current step"
                    : step.state === "failed"
                      ? "ended here"
                      : "not started"}
              </p>
              {step.detail && <p className="mt-0.5 text-xs text-muted">{step.detail}</p>}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
