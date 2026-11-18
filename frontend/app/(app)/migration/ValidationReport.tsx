import { Banner, Card } from "@/components/ui/primitives";
import type { FindingRow } from "@/lib/api/schema";

/**
 * The validation report, split the way it is acted on.
 *
 * Errors block the batch outright. Warnings do not, but they have to be acknowledged
 * in writing by the preparer and are shown again to the approver -- so nobody posts a
 * migration without having read what is doubtful about it.
 */
export function ValidationReport({
  errors,
  warnings,
  acknowledgedBy,
  acknowledgementNote,
}: {
  errors: FindingRow[];
  warnings: FindingRow[];
  acknowledgedBy?: string | null;
  acknowledgementNote?: string | null;
}) {
  return (
    <div className="space-y-4">
      {errors.length === 0 && warnings.length === 0 && (
        <Banner tone="success" title="Every check passed">
          No errors and no warnings. The batch can be submitted for approval.
        </Banner>
      )}

      {errors.length > 0 && (
        <Card
          title={`${errors.length} error${errors.length === 1 ? "" : "s"}`}
          description="These block the load. Correct the CSVs and validate again."
        >
          <FindingList findings={errors} tone="danger" />
        </Card>
      )}

      {warnings.length > 0 && (
        <Card
          title={`${warnings.length} warning${warnings.length === 1 ? "" : "s"}`}
          description="These do not block the load, but they must be acknowledged in writing."
        >
          <FindingList findings={warnings} tone="warning" />
          {acknowledgedBy && (
            <div className="mt-4 rounded-lg bg-success-tint px-4 py-3 text-sm text-success-ink">
              <p className="font-medium">Acknowledged by {acknowledgedBy}</p>
              {acknowledgementNote && <p className="mt-0.5">{acknowledgementNote}</p>}
            </div>
          )}
        </Card>
      )}
    </div>
  );
}

function FindingList({
  findings,
  tone,
}: {
  findings: FindingRow[];
  tone: "danger" | "warning";
}) {
  const toneClass =
    tone === "danger"
      ? "bg-danger-tint text-danger-ink ring-danger-ink/20"
      : "bg-warning-tint text-warning-ink ring-warning-ink/20";

  return (
    <ul className="divide-y divide-border">
      {findings.map((finding, index) => (
        <li key={`${finding.code}-${index}`} className="flex items-start gap-3 py-2.5">
          <span
            className={`inline-flex shrink-0 items-center rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${toneClass}`}
          >
            {finding.code}
          </span>
          <div className="min-w-0">
            <p className="text-sm text-ink">{finding.message}</p>
            {finding.row !== null && finding.row !== undefined && (
              <p className="text-xs text-muted">CSV row {String(finding.row)}</p>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}
