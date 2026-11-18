import type { Metadata } from "next";

import { Money } from "@/components/money/Money";
import { RateBadge } from "@/components/money/Money";
import { StatusPill } from "@/components/ui/StatusPill";
import { Banner, ButtonLink, Card, PageHeader } from "@/components/ui/primitives";
import { apiFetch } from "@/lib/api/server";
import type { ReportLineRow, Statement } from "@/lib/api/schema";
import { formatDate, previousMonthEnd } from "@/lib/format";

export const metadata: Metadata = { title: "Client statement" };

/**
 * The client statement, in the two sections a client reads.
 *
 * Section A is what the mandate owes the client: capital plus profit. Section B is
 * where that money actually is: cash, investments and receivables less payables.
 * The two must be equal to the cent -- that is the A = B test -- and when they are
 * not, the statement is held back rather than issued with a difference on it.
 */
export default async function StatementPage({
  params,
  searchParams,
}: {
  params: Promise<{ clientId: string }>;
  searchParams: Promise<{ from?: string; to?: string }>;
}) {
  const { clientId } = await params;
  const { from, to } = await searchParams;

  const toDate = to ?? previousMonthEnd();
  const fromDate = from ?? `${toDate.slice(0, 4)}-01-01`;

  const statement = await apiFetch<Statement>(
    `/clients/${encodeURIComponent(clientId)}/statement`,
    { query: { from: fromDate, to: toDate } },
  );

  const account = statement.your_account;

  return (
    <div className="space-y-6">
      <PageHeader
        title={statement.client}
        description={`Statement for ${formatDate(statement.from_date)} to ${formatDate(statement.to_date)}, in ${statement.currency}.`}
        actions={
          <>
            <form className="flex flex-wrap items-end gap-2">
              <label className="text-xs text-muted">
                <span className="block">From</span>
                <input
                  type="date"
                  name="from"
                  defaultValue={statement.from_date}
                  className="mt-1 rounded-lg border border-border bg-surface px-3 py-2 text-sm text-ink"
                />
              </label>
              <label className="text-xs text-muted">
                <span className="block">To</span>
                <input
                  type="date"
                  name="to"
                  defaultValue={statement.to_date}
                  className="mt-1 rounded-lg border border-border bg-surface px-3 py-2 text-sm text-ink"
                />
              </label>
              <button
                type="submit"
                className="btn rounded-lg bg-surface px-4 py-2 text-sm font-medium text-ink ring-1 ring-border ring-inset hover:bg-ground"
              >
                Show
              </button>
            </form>
            <ButtonLink
              href={`/api/v1/clients/${encodeURIComponent(clientId)}/statement.pdf?from=${statement.from_date}&to=${statement.to_date}`}
              variant="primary"
              prefetch={false}
            >
              Download PDF
            </ButtonLink>
          </>
        }
      />

      {statement.reconciles ? (
        <Banner tone="success" title="This statement reconciles">
          Section A equals Section B at <Money amount={account.your_balance} />, so the
          statement can be issued to the client.
        </Banner>
      ) : (
        <Banner tone="warning" title="Held: this statement does not reconcile">
          {statement.held_reason ??
            "What the mandate owes the client does not equal what is held for them."}{" "}
          The statement stays on hold until a correcting entry clears the difference.
        </Banner>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card
          title="A · Your account"
          description="What this mandate owes you."
          bodyClassName="px-0 py-0"
        >
          <table className="w-full text-sm">
            <tbody>
              <Row label="Capital brought forward" amount={account.capital_brought_forward} />
              <Row label="Capital paid in and returned" amount={account.capital_movements} />
              <Row label="Profit brought forward" amount={account.profit_brought_forward} />
              <Row label="Profit earned in closed months" amount={account.profit_earned_closed} />
              <Row
                label="Profit earned, month not yet closed"
                amount={account.profit_open_period}
              />
              <Row label="Management fees charged" amount={account.fees_charged} />
              <Row label="Profit paid out to you" amount={account.profit_paid} />
              {!/^-?0+(\.0+)?$/.test(account.profit_other_movements) && (
                <Row label="Other profit movements" amount={account.profit_other_movements} />
              )}
              <tr className="border-t-2 border-ink/15 bg-ground">
                <th scope="row" className="px-5 py-3 text-sm font-semibold text-ink">
                  Your balance (A)
                </th>
                <td className="px-5 py-3 text-right">
                  <Money
                    amount={account.your_balance}
                    currency={statement.currency}
                    className="text-base font-semibold"
                  />
                </td>
              </tr>
            </tbody>
          </table>
        </Card>

        <Card
          title="B · Where it is held"
          description="The assets and liabilities behind that balance."
          bodyClassName="px-0 py-0"
        >
          <table className="w-full text-sm">
            <tbody>
              <SectionHeading label="Assets" />
              {statement.where_held.assets.map((line) => (
                <LineRow key={line.code} line={line} />
              ))}
              {statement.where_held.less_payables.length > 0 && (
                <>
                  <SectionHeading label="Less payables" />
                  {statement.where_held.less_payables.map((line) => (
                    <LineRow key={line.code} line={line} negate />
                  ))}
                </>
              )}
              <tr className="border-t-2 border-ink/15 bg-ground">
                <th scope="row" className="px-5 py-3 text-sm font-semibold text-ink">
                  Net holdings (B)
                </th>
                <td className="px-5 py-3 text-right">
                  <Money
                    amount={statement.where_held.net_holdings}
                    currency={statement.currency}
                    className="text-base font-semibold"
                  />
                </td>
              </tr>
            </tbody>
          </table>
        </Card>
      </div>

      <Card
        title="Your investments"
        description="Every holding in this mandate at the end of the period."
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
                <th scope="col" className="px-3 py-2 text-right">
                  Outstanding
                </th>
                <th scope="col" className="px-3 py-2 text-right">
                  Accrued profit
                </th>
                <th scope="col" className="px-3 py-2">
                  Expected profit rate
                </th>
                <th scope="col" className="px-3 py-2">
                  Matures
                </th>
                <th scope="col" className="px-5 py-2">
                  Status
                </th>
              </tr>
            </thead>
            <tbody>
              {statement.holdings.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-5 py-8 text-center text-muted">
                    No investments were held in this period.
                  </td>
                </tr>
              )}
              {statement.holdings.map((holding) => (
                <tr key={holding.id} className="border-t border-border">
                  <td className="px-5 py-2.5 font-medium">{holding.id}</td>
                  <td className="px-3 py-2.5 text-muted">
                    {holding.asset_class.replace(/_/g, " ").toLowerCase()}
                  </td>
                  <td className="px-3 py-2.5 text-right">
                    <Money amount={holding.outstanding} currency={holding.currency} />
                  </td>
                  <td className="px-3 py-2.5 text-right">
                    <Money amount={holding.accrued_profit} muteZero />
                  </td>
                  <td className="px-3 py-2.5">
                    <RateBadge rate={holding.profit_rate} />
                  </td>
                  <td className="px-3 py-2.5 text-muted">{formatDate(holding.maturity_date)}</td>
                  <td className="px-5 py-2.5">
                    <StatusPill state={holding.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <p className="text-xs text-muted">
        Your money and assets are held in trust by the appointed custodian bank in an
        account in your name, segregated from the firm&rsquo;s own assets and from those
        of every other client. Profit is earned on Shariah-compliant terms; no interest
        is charged or received.
      </p>
    </div>
  );
}

function Row({ label, amount }: { label: string; amount: string }) {
  return (
    <tr className="border-t border-border first:border-0">
      <th scope="row" className="px-5 py-2.5 font-normal text-muted">
        {label}
      </th>
      <td className="px-5 py-2.5 text-right">
        <Money amount={amount} muteZero />
      </td>
    </tr>
  );
}

function SectionHeading({ label }: { label: string }) {
  return (
    <tr className="border-t border-border bg-ground/60">
      <th
        scope="colgroup"
        colSpan={2}
        className="px-5 py-1.5 text-xs font-semibold tracking-wide text-muted uppercase"
      >
        {label}
      </th>
    </tr>
  );
}

/**
 * One balance sheet line.
 *
 * Payables arrive as positive amounts under a "less payables" heading, so they are
 * shown as they read on a statement rather than re-signed here.
 */
function LineRow({ line, negate = false }: { line: ReportLineRow; negate?: boolean }) {
  return (
    <tr className="border-t border-border">
      <th scope="row" className="px-5 py-2.5 font-normal">
        <span className="text-ink">{line.name}</span>
        <span className="tnum ml-2 text-xs text-muted">{line.code}</span>
      </th>
      <td className="px-5 py-2.5 text-right">
        {negate ? <span className="tnum text-muted">(</span> : null}
        <Money amount={line.amount} />
        {negate ? <span className="tnum text-muted">)</span> : null}
      </td>
    </tr>
  );
}
