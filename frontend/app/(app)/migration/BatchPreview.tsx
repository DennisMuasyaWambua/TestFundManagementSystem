import { Money } from "@/components/money/Money";
import { Banner, Card, Stat } from "@/components/ui/primitives";
import type { PreviewBody } from "@/lib/api/schema";
import { formatDate } from "@/lib/format";
import { isZero } from "@/lib/money";

/**
 * The journal exactly as it will post, and the statement exactly as it will read.
 *
 * An approver sees this before approving: the totals, whether debits equal credits,
 * whether A will equal B, and every line grouped by account. Nothing has been posted
 * at this point -- these rows are still in the staging tables.
 */
export function BatchPreview({ preview }: { preview: PreviewBody }) {
  const holdings = preview.holdings as unknown as Record<string, unknown>[];

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="Total debits"
          value={<Money amount={preview.total_debit} />}
          tone={preview.balanced ? "success" : "danger"}
        />
        <Stat
          label="Total credits"
          value={<Money amount={preview.total_credit} />}
          tone={preview.balanced ? "success" : "danger"}
        />
        <Stat
          label="Section A · owed to the client"
          value={<Money amount={preview.section_a} />}
          hint="Capital plus profit"
        />
        <Stat
          label="Section B · net holdings"
          value={<Money amount={preview.section_b} />}
          tone={preview.reconciles ? "success" : "warning"}
          hint="Assets less payables"
        />
      </div>

      {!preview.balanced && (
        <Banner tone="danger" title="This journal does not balance">
          Debits and credits must be equal to the cent before the batch can be posted.
        </Banner>
      )}

      {preview.reconciles ? (
        <Banner tone="success" title="A will equal B">
          The client statement will reconcile at <Money amount={preview.section_a} /> as at{" "}
          {formatDate(preview.cutover_date)}.
        </Banner>
      ) : (
        <Banner tone="warning" title="A will not equal B">
          The difference of <Money amount={preview.suspense} /> is carried on suspense
          (1390). Statements for this mandate stay on hold until a correcting entry
          clears it.
        </Banner>
      )}

      <Card
        title="The opening journal"
        description={`One entry dated ${formatDate(preview.cutover_date)}, grouped by account.`}
        bodyClassName="px-0 py-0"
      >
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-ground">
              <tr className="text-xs tracking-wide text-muted uppercase">
                <th scope="col" className="px-5 py-2">
                  Account
                </th>
                <th scope="col" className="px-3 py-2">
                  Holding
                </th>
                <th scope="col" className="px-3 py-2">
                  Currency
                </th>
                <th scope="col" className="px-3 py-2 text-right">
                  Debit
                </th>
                <th scope="col" className="px-5 py-2 text-right">
                  Credit
                </th>
              </tr>
            </thead>
            <tbody>
              {preview.lines.map((line, index) => (
                <tr key={`${line.account_code}-${line.holding_id ?? ""}-${index}`} className="border-t border-border">
                  <td className="px-5 py-2.5">
                    <span className="tnum font-medium">{line.account_code}</span>{" "}
                    <span className="text-ink">{line.account_name}</span>
                    <p className="text-xs text-muted">
                      {line.description}
                      {line.derived && (
                        <span className="ml-1 text-warning-ink">· derived, not from the CSV</span>
                      )}
                    </p>
                  </td>
                  <td className="px-3 py-2.5 text-muted">{line.holding_id ?? "—"}</td>
                  <td className="px-3 py-2.5">{line.currency}</td>
                  <td className="px-3 py-2.5 text-right">
                    {isZero(line.debit) ? (
                      <span className="text-muted">—</span>
                    ) : (
                      <Money amount={line.debit} />
                    )}
                  </td>
                  <td className="px-5 py-2.5 text-right">
                    {isZero(line.credit) ? (
                      <span className="text-muted">—</span>
                    ) : (
                      <Money amount={line.credit} />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t-2 border-ink/15 bg-ground font-semibold">
                <td className="px-5 py-3" colSpan={3}>
                  Total
                </td>
                <td className="px-3 py-3 text-right">
                  <Money amount={preview.total_debit} />
                </td>
                <td className="px-5 py-3 text-right">
                  <Money amount={preview.total_credit} />
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      </Card>

      <Card
        title={`Holdings to be created (${holdings.length})`}
        description="Each becomes an active holding, accruing from the day after cutover."
        bodyClassName="px-0 py-0"
      >
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-ground">
              <tr className="text-xs tracking-wide text-muted uppercase">
                <th scope="col" className="px-5 py-2">
                  Deal
                </th>
                <th scope="col" className="px-3 py-2">
                  Asset class
                </th>
                <th scope="col" className="px-3 py-2">
                  Counterparty
                </th>
                <th scope="col" className="px-3 py-2 text-right">
                  Cost
                </th>
                <th scope="col" className="px-3 py-2 text-right">
                  Opening accrued
                </th>
                <th scope="col" className="px-5 py-2">
                  Matures
                </th>
              </tr>
            </thead>
            <tbody>
              {holdings.map((row, index) => (
                <tr key={`${String(row.holding_id)}-${index}`} className="border-t border-border">
                  <td className="px-5 py-2.5 font-medium">
                    {String(row.holding_id ?? "")}
                    {row.is_placeholder === true && (
                      <p className="text-xs text-warning-ink">placeholder terms</p>
                    )}
                  </td>
                  <td className="px-3 py-2.5 text-muted">{String(row.asset_class ?? "")}</td>
                  <td className="px-3 py-2.5 text-muted">{String(row.counterparty ?? "")}</td>
                  <td className="px-3 py-2.5 text-right">
                    <Money amount={asMoney(row.face_amount)} />
                  </td>
                  <td className="px-3 py-2.5 text-right">
                    <Money amount={asMoney(row.opening_accrued)} muteZero />
                    {row.expected_accrual !== null && row.expected_accrual !== undefined && (
                      <p className="text-xs text-muted">
                        recomputed <Money amount={asMoney(row.expected_accrual)} />
                      </p>
                    )}
                  </td>
                  <td className="px-5 py-2.5 text-muted">
                    {formatDate(asText(row.maturity_date))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

function asMoney(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function asText(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}
