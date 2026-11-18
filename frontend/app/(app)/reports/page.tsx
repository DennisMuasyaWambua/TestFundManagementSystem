import type { Metadata } from "next";

import { Money } from "@/components/money/Money";
import {
  Banner,
  ButtonLink,
  Card,
  EmptyState,
  PageHeader,
  Stat,
} from "@/components/ui/primitives";
import { apiFetch, apiFetchOrNull } from "@/lib/api/server";
import type {
  BalanceSheet,
  ClientRow,
  PortfolioSummary,
  ProfitAndLoss,
  SectionTotalRow,
  TrialBalance,
} from "@/lib/api/schema";
import { formatDate, humanise, previousMonthEnd } from "@/lib/format";

export const metadata: Metadata = { title: "Reports" };

/** The CMA reporting rhythm from Licensing reg 40(1), as pickable presets. */
const PRESETS = [
  { key: "monthly", label: "Monthly" },
  { key: "quarterly", label: "Quarterly (due within 15 days)" },
  { key: "half-yearly", label: "Half-yearly (due within 30 days)" },
  { key: "annual", label: "Annual" },
] as const;

export default async function ReportsPage({
  searchParams,
}: {
  searchParams: Promise<{ as_of?: string; client?: string; from?: string }>;
}) {
  const { as_of, client, from } = await searchParams;
  const asOf = as_of ?? previousMonthEnd();
  const fromDate = from ?? `${asOf.slice(0, 4)}-01-01`;

  const clients = await apiFetch<ClientRow[]>("/clients");
  const clientId = client ?? clients[0]?.id ?? "";

  const [trialBalance, portfolio, balanceSheet, profitAndLoss] = await Promise.all([
    apiFetch<TrialBalance>("/reports/trial-balance", {
      query: { as_of: asOf, client: client ?? null },
    }),
    apiFetch<PortfolioSummary>("/reports/portfolio-summary", { query: { as_of: asOf } }),
    clientId
      ? apiFetchOrNull<BalanceSheet>(`/clients/${encodeURIComponent(clientId)}/balance-sheet`, {
          query: { as_of: asOf },
        })
      : Promise.resolve(null),
    clientId
      ? apiFetchOrNull<ProfitAndLoss>(
          `/clients/${encodeURIComponent(clientId)}/profit-and-loss`,
          { query: { from: fromDate, to: asOf } },
        )
      : Promise.resolve(null),
  ]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Reports"
        description="Trial balance, balance sheet and profit and loss per mandate, plus the portfolio summary the CMA requires."
        actions={
          <form className="flex flex-wrap items-end gap-2">
            <label className="text-xs text-muted">
              <span className="block">Client</span>
              <select
                name="client"
                defaultValue={client ?? ""}
                className="mt-1 rounded-lg border border-border bg-surface px-3 py-2 text-sm text-ink"
              >
                <option value="">All mandates</option>
                {clients.map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.legal_name}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs text-muted">
              <span className="block">From</span>
              <input
                type="date"
                name="from"
                defaultValue={fromDate}
                className="mt-1 rounded-lg border border-border bg-surface px-3 py-2 text-sm text-ink"
              />
            </label>
            <label className="text-xs text-muted">
              <span className="block">As at</span>
              <input
                type="date"
                name="as_of"
                defaultValue={asOf}
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
        }
      />

      <Card
        title="Portfolio summary for the CMA"
        description={`${portfolio.number_of_clients} client${portfolio.number_of_clients === 1 ? "" : "s"} as at ${formatDate(portfolio.as_of)}.`}
        actions={
          <ButtonLink
            href={`/api/v1/reports/portfolio-summary.xlsx?as_of=${asOf}`}
            prefetch={false}
          >
            Download XLSX
          </ButtonLink>
        }
        bodyClassName="px-0 py-0"
      >
        <div className="flex flex-wrap gap-2 px-5 py-4">
          {PRESETS.map((preset) => (
            <span
              key={preset.key}
              className="rounded-md bg-ground px-2.5 py-1 text-xs text-muted ring-1 ring-border ring-inset"
            >
              {preset.label}
            </span>
          ))}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-ground">
              <tr className="text-xs tracking-wide text-muted uppercase">
                <th scope="col" className="px-5 py-2">
                  Client
                </th>
                <th scope="col" className="px-3 py-2">
                  Asset class
                </th>
                <th scope="col" className="px-3 py-2 text-right">
                  Deals
                </th>
                <th scope="col" className="px-3 py-2 text-right">
                  Cost
                </th>
                <th scope="col" className="px-3 py-2 text-right">
                  Accrued profit
                </th>
                <th scope="col" className="px-5 py-2 text-right">
                  Fair value
                </th>
              </tr>
            </thead>
            <tbody>
              {portfolio.rows.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-5 py-8 text-center text-muted">
                    Nothing is invested at this date.
                  </td>
                </tr>
              )}
              {portfolio.rows.map((row) => (
                <tr key={`${row.client_id}-${row.asset_class}`} className="border-t border-border">
                  <td className="px-5 py-2.5">{row.client}</td>
                  <td className="px-3 py-2.5 text-muted">{humanise(row.asset_class)}</td>
                  <td className="tnum px-3 py-2.5 text-right">{row.count}</td>
                  <td className="px-3 py-2.5 text-right">
                    <Money amount={row.cost} />
                  </td>
                  <td className="px-3 py-2.5 text-right">
                    <Money amount={row.accrued_profit} muteZero />
                  </td>
                  <td className="px-5 py-2.5 text-right">
                    <Money amount={row.fair_value} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {portfolio.cash.length > 0 && (
          <div className="overflow-x-auto border-t border-border">
            <table className="w-full text-sm">
              <caption className="px-5 pt-4 pb-2 text-left text-xs font-semibold tracking-wide text-muted uppercase">
                Cash at custodians
              </caption>
              <thead className="bg-ground">
                <tr className="text-xs tracking-wide text-muted uppercase">
                  <th scope="col" className="px-5 py-2">
                    Client
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Custodian
                  </th>
                  <th scope="col" className="px-3 py-2 text-right">
                    Balance
                  </th>
                  <th scope="col" className="px-5 py-2 text-right">
                    In base currency
                  </th>
                </tr>
              </thead>
              <tbody>
                {portfolio.cash.map((row) => (
                  <tr
                    key={`${row.client_id}-${row.account_number}`}
                    className="border-t border-border"
                  >
                    <td className="px-5 py-2.5">{row.client_id}</td>
                    <td className="px-3 py-2.5 text-muted">
                      {row.custodian}
                      <p className="tnum text-xs">{row.account_number}</p>
                    </td>
                    <td className="px-3 py-2.5 text-right">
                      <Money amount={row.balance} currency={row.currency} />
                    </td>
                    <td className="px-5 py-2.5 text-right">
                      <Money amount={row.base_amount} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card
        title="Trial balance"
        description={`${client ?? "Every mandate"} as at ${formatDate(trialBalance.as_of)}.`}
        bodyClassName="px-0 py-0"
      >
        {!trialBalance.balanced && (
          <div className="px-5 pt-4">
            <Banner tone="danger" title="The trial balance does not balance">
              This should be impossible: every entry is validated as balancing before it
              is written. Raise it with finance immediately.
            </Banner>
          </div>
        )}
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-ground">
              <tr className="text-xs tracking-wide text-muted uppercase">
                <th scope="col" className="px-5 py-2">
                  Account
                </th>
                <th scope="col" className="px-3 py-2">
                  Type
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
              {trialBalance.rows.map((row) => (
                <tr key={row.code} className="border-t border-border">
                  <td className="px-5 py-2">
                    <span className="tnum font-medium">{row.code}</span> {row.name}
                  </td>
                  <td className="px-3 py-2 text-muted">{humanise(row.type)}</td>
                  <td className="px-3 py-2 text-right">
                    <Money amount={row.debit} muteZero />
                  </td>
                  <td className="px-5 py-2 text-right">
                    <Money amount={row.credit} muteZero />
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t-2 border-ink/15 bg-ground font-semibold">
                <td className="px-5 py-3" colSpan={2}>
                  Total
                </td>
                <td className="px-3 py-3 text-right">
                  <Money amount={trialBalance.total_debit} />
                </td>
                <td className="px-5 py-3 text-right">
                  <Money amount={trialBalance.total_credit} />
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      </Card>

      {balanceSheet && (
        <Card
          title={`Balance sheet · ${balanceSheet.client}`}
          description={`As at ${formatDate(balanceSheet.as_of)}, in ${balanceSheet.currency}.`}
        >
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            <Section section={balanceSheet.assets} />
            <Section section={balanceSheet.liabilities} />
            <Section section={balanceSheet.client_funds} />
          </div>
          <p className="mt-4 border-t border-border pt-4 text-xs text-muted">
            Client money is a liability of the firm, never its own asset. Firm equity
            accounts carry no client balance: the retained result shown here is{" "}
            <Money amount={balanceSheet.retained_result} />.
          </p>
        </Card>
      )}

      {profitAndLoss && (
        <Card
          title={`Profit and loss · ${profitAndLoss.client}`}
          description={`${formatDate(profitAndLoss.from_date)} to ${formatDate(profitAndLoss.to_date)}, in ${profitAndLoss.currency}. The month-end closing entry is excluded, so each period still shows what it earned.`}
        >
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <Section section={profitAndLoss.income} />
            <Section section={profitAndLoss.expenses} />
          </div>
          <div className="mt-4 border-t border-border pt-4">
            <Stat
              label="Net profit for the period"
              value={<Money amount={profitAndLoss.net_profit} />}
            />
          </div>
        </Card>
      )}

      {!balanceSheet && clientId === "" && (
        <EmptyState title="Choose a mandate to see its balance sheet and profit and loss" />
      )}
    </div>
  );
}

function Section({ section }: { section: SectionTotalRow }) {
  return (
    <div>
      <h3 className="text-xs font-semibold tracking-wide text-muted uppercase">
        {section.label}
      </h3>
      <table className="mt-2 w-full text-sm">
        <tbody>
          {section.lines.length === 0 && (
            <tr>
              <td className="py-2 text-muted" colSpan={2}>
                Nothing in this section.
              </td>
            </tr>
          )}
          {section.lines.map((line) => (
            <tr key={line.code} className="border-b border-border">
              <th scope="row" className="py-2 pr-3 font-normal">
                <span className="tnum text-xs text-muted">{line.code}</span> {line.name}
              </th>
              <td className="py-2 text-right">
                <Money amount={line.amount} />
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="font-semibold">
            <td className="py-2">Total</td>
            <td className="py-2 text-right">
              <Money amount={section.total} />
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}
