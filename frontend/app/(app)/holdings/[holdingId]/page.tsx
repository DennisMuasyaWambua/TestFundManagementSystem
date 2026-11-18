import type { Metadata } from "next";
import Link from "next/link";

import { HoldingReceipts } from "@/app/(app)/holdings/[holdingId]/HoldingReceipts";
import { ProposeValuation } from "@/app/(app)/valuations/ProposeValuation";
import { Money, RateBadge } from "@/components/money/Money";
import { StatusPill } from "@/components/ui/StatusPill";
import {
  Banner,
  Card,
  EmptyState,
  Field,
  FieldList,
  PageHeader,
  Stat,
} from "@/components/ui/primitives";
import { apiFetch } from "@/lib/api/server";
import type { HoldingDetail } from "@/lib/api/schema";
import { requireUser } from "@/lib/auth/me";
import { PERMISSION, can } from "@/lib/auth/permissions";
import { formatDate, humanise } from "@/lib/format";

export const metadata: Metadata = { title: "Holding" };

export default async function HoldingPage({
  params,
}: {
  params: Promise<{ holdingId: string }>;
}) {
  const { holdingId } = await params;
  const me = await requireUser();

  const detail = await apiFetch<HoldingDetail>(`/holdings/${encodeURIComponent(holdingId)}`);
  const { holding, balances } = detail;

  const revaluable = holding.asset_class === "SUKUK" || holding.asset_class === "PROPERTY";

  return (
    <div className="space-y-6">
      <PageHeader
        title={holding.id}
        description={`${humanise(holding.asset_class)} · ${holding.counterparty}`}
        actions={<StatusPill state={holding.status} />}
      />

      {holding.is_placeholder && (
        <Banner tone="warning" title="The terms of this holding are still a placeholder">
          No profit can be accrued until the real terms are recorded. This holding is
          excluded from the accrual run and is listed as skipped on each one.
        </Banner>
      )}

      {holding.related_party && (
        <Banner tone="warning" title="Related-party counterparty">
          Investments in related companies are limited to 10% of funds managed
          (Licensing reg 39(3)). The limit is checked when an instruction is raised.
        </Banner>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="Outstanding"
          value={<Money amount={balances.outstanding} currency={holding.currency} />}
          hint="From the ledger"
        />
        <Stat
          label="Accrued profit"
          value={<Money amount={balances.accrued_profit} />}
          hint={`Profit to date ${balances.profit_to_date}`}
        />
        <Stat
          label="Income recognised"
          value={<Money amount={balances.income_recognised} />}
          hint={`Fees charged ${balances.fee_charged}`}
        />
        <Stat
          label={revaluable ? "Fair value" : "Carrying amount"}
          value={<Money amount={balances.fair_value} />}
          hint={
            revaluable
              ? `Cost ${holding.face_amount}, adjustment ${balances.fair_value_adjustment}`
              : "Cost less repayments"
          }
        />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card title="Terms" className="lg:col-span-2">
          <FieldList cols={3}>
            <Field label="Client">
              <Link href={`/clients/${holding.client_id}`} className="text-accent underline">
                {holding.client_id}
              </Link>
            </Field>
            <Field label="Custody account">{holding.custody_account_id}</Field>
            <Field label="Currency">{holding.currency}</Field>
            <Field label="Cost">
              <Money amount={holding.face_amount} currency={holding.currency} />
            </Field>
            {holding.nominal && (
              <Field label="Nominal (face) value">
                <Money amount={holding.nominal} currency={holding.currency} />
              </Field>
            )}
            <Field label="Expected profit rate">
              <RateBadge rate={holding.profit_rate} />
            </Field>
            <Field label="Day basis">{holding.day_basis}</Field>
            <Field label="Started">{formatDate(holding.start_date)}</Field>
            <Field label="Matures">{formatDate(holding.maturity_date)}</Field>
            {holding.monthly_rent && (
              <Field label="Monthly rent">
                <Money amount={holding.monthly_rent} currency={holding.currency} />
              </Field>
            )}
            <Field label="Accrual starts">{formatDate(holding.accrual_start)}</Field>
            <Field label="Opening accrued profit">
              <Money amount={holding.opening_accrued} muteZero />
            </Field>
            <Field label="Shariah approval">
              {holding.shariah_cert_ref ?? (
                <span className="text-warning-ink">not recorded</span>
              )}
            </Field>
            <Field label="Counterparty reference">{holding.external_ref ?? "—"}</Field>
          </FieldList>
          {holding.description && (
            <p className="mt-4 border-t border-border pt-4 text-sm text-muted">
              {holding.description}
            </p>
          )}
        </Card>

        <Card title="Valuations" description="Cost is never overwritten.">
          {detail.valuations.length === 0 ? (
            <EmptyState
              title="Not revalued"
              description={
                revaluable
                  ? "Propose a valuation to carry this holding at fair value."
                  : "This asset class is carried at cost less repayments."
              }
            />
          ) : (
            <ul className="space-y-3">
              {detail.valuations.map((valuation) => (
                <li key={valuation.id} className="border-b border-border pb-3 last:border-0">
                  <div className="flex items-center justify-between gap-2">
                    <Money amount={valuation.value} className="text-sm font-medium" />
                    <StatusPill state={valuation.status} />
                  </div>
                  <p className="mt-0.5 text-xs text-muted">
                    {formatDate(valuation.valuation_date)}
                    {valuation.price ? ` · price ${valuation.price} per 100` : ""}
                  </p>
                  <p className="text-xs text-muted">{valuation.source}</p>
                  {valuation.valuer_name && (
                    <p className="text-xs text-muted">
                      {valuation.valuer_name}
                      {valuation.report_ref ? ` · ${valuation.report_ref}` : ""}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <HoldingReceipts
        detail={detail}
        canRecord={can(me, PERMISSION.receiptRecord)}
        canOperate={can(me, PERMISSION.ledgerOperations)}
      />

      {revaluable && can(me, PERMISSION.valuationPropose) && (
        <ProposeValuation
          holdingId={holding.id}
          assetClass={holding.asset_class}
          currency={holding.currency}
        />
      )}

      <Card
        title="Journal"
        description="Every entry that has touched this holding, newest first."
        bodyClassName="px-0 py-0"
      >
        {detail.journal.length === 0 ? (
          <div className="p-5">
            <EmptyState title="Nothing posted yet" />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-ground">
                <tr className="text-xs tracking-wide text-muted uppercase">
                  <th scope="col" className="px-5 py-2">
                    Date
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Event
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Narrative
                  </th>
                  <th scope="col" className="px-5 py-2">
                    Reference
                  </th>
                </tr>
              </thead>
              <tbody>
                {detail.journal.map((entry) => (
                  <tr key={entry.id} className="border-t border-border">
                    <td className="px-5 py-2.5">{formatDate(entry.entry_date)}</td>
                    <td className="px-3 py-2.5">{humanise(entry.event)}</td>
                    <td className="px-3 py-2.5 text-muted">{entry.narrative}</td>
                    <td className="px-5 py-2.5 text-muted">
                      <Link href={`/journal?entry=${entry.id}`} className="underline">
                        {entry.reference ?? `#${entry.id}`}
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
