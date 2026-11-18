import type { Metadata } from "next";

import { FxRateForm } from "@/app/(app)/fx-rates/FxRateForm";
import { FxRateValue } from "@/components/money/Money";
import { Banner, Card, EmptyState, PageHeader } from "@/components/ui/primitives";
import { apiFetch } from "@/lib/api/server";
import type { FxRateRow } from "@/lib/api/schema";
import { formatDate, todayIso } from "@/lib/format";

export const metadata: Metadata = { title: "Exchange rates" };

export default async function FxRatesPage() {
  const rates = await apiFetch<FxRateRow[]>("/fx-rates", { query: { limit: 200 } });
  const today = todayIso();

  // Group by currency pair so the most recent rate for each is obvious: that is the
  // one the ledger will pick up for a posting dated today.
  const byPair = new Map<string, FxRateRow[]>();
  for (const rate of rates) {
    const key = `${rate.currency}/${rate.base_currency}`;
    byPair.set(key, [...(byPair.get(key) ?? []), rate]);
  }
  for (const list of byPair.values()) {
    list.sort((a, b) => b.rate_date.localeCompare(a.rate_date));
  }

  const stale = [...byPair.entries()].filter(([, list]) => {
    const latest = list[0];
    return latest !== undefined && latest.rate_date < today;
  });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Exchange rates"
        description="Every journal line carries its own rate and its base-currency amount. A posting with no rate on or before its date is refused outright."
      />

      {stale.length > 0 && (
        <Banner tone="warning" title="No rate entered for today">
          {stale
            .map(([pair, list]) => `${pair} (latest ${formatDate(list[0]?.rate_date)})`)
            .join(", ")}
          . A posting dated today will use the latest rate on or before it, which is
          correct for a back-dated entry but not for today&rsquo;s revaluation.
        </Banner>
      )}

      <FxRateForm defaultDate={today} />

      {byPair.size === 0 ? (
        <EmptyState
          title="No rates yet"
          description="Until a rate exists, nothing can be posted in a currency other than a mandate's base currency."
        />
      ) : (
        [...byPair.entries()].map(([pair, list]) => (
          <Card
            key={pair}
            title={pair}
            description={`${list.length} rate${list.length === 1 ? "" : "s"} on file, most recent first.`}
            bodyClassName="px-0 py-0"
          >
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-ground">
                  <tr className="text-xs tracking-wide text-muted uppercase">
                    <th scope="col" className="px-5 py-2">
                      Date
                    </th>
                    <th scope="col" className="px-3 py-2 text-right">
                      Rate
                    </th>
                    <th scope="col" className="px-3 py-2">
                      Source
                    </th>
                    <th scope="col" className="px-5 py-2">
                      Entered by
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {list.slice(0, 20).map((rate) => (
                    <tr key={rate.id} className="border-t border-border">
                      <td className="px-5 py-2.5">{formatDate(rate.rate_date)}</td>
                      <td className="px-3 py-2.5 text-right">
                        <FxRateValue rate={rate.rate} />
                      </td>
                      <td className="px-3 py-2.5 text-muted">{rate.source}</td>
                      <td className="px-5 py-2.5 text-muted">{rate.entered_by}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        ))
      )}
    </div>
  );
}
