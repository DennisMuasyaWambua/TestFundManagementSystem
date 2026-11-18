import type { ReactNode } from "react";

import { StatusPill } from "@/components/ui/StatusPill";

/**
 * One line of the month-end checklist.
 *
 * The state words come straight from the backend checklist (DONE, TODO, BLOCKED,
 * OVERRIDDEN) so the screen cannot disagree with the rule that decides whether the
 * period may be closed.
 */
export function ChecklistItem({
  label,
  state,
  detail,
  action,
}: {
  label: string;
  state: string;
  detail?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <li className="flex flex-wrap items-start justify-between gap-3 border-b border-border py-3 last:border-0">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-sm font-medium text-ink">{label}</p>
          <StatusPill state={state} />
        </div>
        {detail && <div className="mt-1 text-sm text-muted">{detail}</div>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </li>
  );
}

export function Checklist({ children }: { children: ReactNode }) {
  return <ul className="divide-border">{children}</ul>;
}
