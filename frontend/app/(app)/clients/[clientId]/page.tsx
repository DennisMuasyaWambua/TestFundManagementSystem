import type { Metadata } from "next";
import Link from "next/link";

import { Money, RateBadge } from "@/components/money/Money";
import { StatusPill } from "@/components/ui/StatusPill";
import {
  Banner,
  ButtonLink,
  Card,
  EmptyState,
  Field,
  FieldList,
  PageHeader,
} from "@/components/ui/primitives";
import { apiFetch, apiFetchOrNull } from "@/lib/api/server";
import type {
  ClientRow,
  CustodyAccountRow,
  HoldingListRow,
  MandateFeeRow,
  RoleMappingRow,
} from "@/lib/api/schema";
import { requireUser } from "@/lib/auth/me";
import { PERMISSION, can } from "@/lib/auth/permissions";
import { formatDate, humanise } from "@/lib/format";
import { formatRatePct } from "@/lib/money";

export const metadata: Metadata = { title: "Client" };

export default async function ClientDetailPage({
  params,
}: {
  params: Promise<{ clientId: string }>;
}) {
  const { clientId } = await params;
  const me = await requireUser();
  const id = encodeURIComponent(clientId);

  const [client, custody, fees, holdings, roles] = await Promise.all([
    apiFetch<ClientRow>(`/clients/${id}`),
    apiFetch<CustodyAccountRow[]>(`/clients/${id}/custody-accounts`),
    apiFetch<MandateFeeRow[]>(`/clients/${id}/fees`),
    apiFetch<HoldingListRow[]>("/holdings", { query: { client: clientId } }),
    apiFetchOrNull<RoleMappingRow[]>("/role-mappings", { query: { client: clientId } }),
  ]);

  return (
    <div className="space-y-6">
      <PageHeader
        title={client.legal_name}
        description={`${client.id} · reporting in ${client.base_currency}`}
        actions={
          <>
            <ButtonLink href={`/clients/${id}/statement`}>Statement</ButtonLink>
            <ButtonLink href={`/holdings?client=${id}`}>Holdings</ButtonLink>
            {can(me, PERMISSION.journalView) && (
              <ButtonLink href={`/journal?client=${id}`}>Journal</ButtonLink>
            )}
          </>
        }
      />

      {client.onboarding_gaps.length > 0 && (
        <Banner tone="warning" title="Onboarding is not complete">
          No custody instruction can be raised for this mandate until these are in
          place:
          <ul className="mt-1 list-inside list-disc">
            {client.onboarding_gaps.map((gap) => (
              <li key={gap}>{gap}</li>
            ))}
          </ul>
        </Banner>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card title="Mandate" className="lg:col-span-2">
          <FieldList cols={3}>
            <Field label="Legal name">{client.legal_name}</Field>
            <Field label="Base currency">{client.base_currency}</Field>
            <Field label="Record status">
              <StatusPill state={client.status} />
            </Field>
            <Field label="Agreement reference">
              {client.agreement_ref ?? (
                <span className="text-warning-ink">not on file (CoB reg 13)</span>
              )}
            </Field>
            <Field label="Agreement date">{formatDate(client.agreement_date)}</Field>
            <Field label="Final withholding tax">
              {formatRatePct(client.final_wht_rate)}
            </Field>
          </FieldList>
        </Card>

        <Card title="Know your customer" description="Recorded by compliance.">
          <FieldList cols={1}>
            <Field label="KYC status">
              <StatusPill
                state={client.kyc_status}
                tone={client.kyc_status === "APPROVED" ? "success" : "warning"}
              />
            </Field>
            <Field label="AML risk rating">
              {client.aml_risk_rating ? humanise(client.aml_risk_rating) : "not rated"}
            </Field>
            <Field label="Last reviewed">{formatDate(client.kyc_reviewed_on)}</Field>
          </FieldList>
        </Card>
      </div>

      <Card
        title="Custody accounts"
        description="Each account is held by an appointed custodian in the client's own name."
        bodyClassName="px-0 py-0"
      >
        {custody.length === 0 ? (
          <div className="p-5">
            <EmptyState title="No custody account yet" />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-ground">
                <tr className="text-xs tracking-wide text-muted uppercase">
                  <th scope="col" className="px-5 py-2">
                    Custodian
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Account number
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Currency
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Cash ledger
                  </th>
                  <th scope="col" className="px-5 py-2">
                    Custody appointment
                  </th>
                </tr>
              </thead>
              <tbody>
                {custody.map((account) => (
                  <tr key={account.id} className="border-t border-border">
                    <td className="px-5 py-3">
                      <p className="font-medium">{account.custodian}</p>
                      <p className="text-xs text-muted">{account.custodian_address}</p>
                    </td>
                    <td className="tnum px-3 py-3">
                      {account.account_number}
                      {account.is_default && (
                        <span className="ml-2 text-xs text-muted">(default)</span>
                      )}
                    </td>
                    <td className="px-3 py-3">{account.currency}</td>
                    <td className="tnum px-3 py-3 text-muted">
                      {account.cash_ledger_code} / {account.wakala_ledger_code}
                    </td>
                    <td className="px-5 py-3">
                      {account.custody_agreement_ref ?? (
                        <span className="text-warning-ink">
                          not on file (Licensing reg 42)
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card
          title="Management fees"
          description="Charged as a percentage of the income earned, per asset class."
        >
          {fees.length === 0 ? (
            <EmptyState title="No fee basis recorded" />
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-xs tracking-wide text-muted uppercase">
                  <th scope="col" className="py-2">
                    Asset class
                  </th>
                  <th scope="col" className="py-2">
                    Fee
                  </th>
                  <th scope="col" className="py-2">
                    Effective from
                  </th>
                </tr>
              </thead>
              <tbody>
                {fees.map((fee) => (
                  <tr
                    key={`${fee.asset_class}-${fee.effective_from}`}
                    className="border-b border-border last:border-0"
                  >
                    <td className="py-2">{humanise(fee.asset_class)}</td>
                    <td className="py-2">
                      <RateBadge rate={fee.fee_pct_of_income} />
                    </td>
                    <td className="py-2 text-muted">{formatDate(fee.effective_from)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>

        <Card
          title="Ledger accounts"
          description="How this mandate's roles resolve to account codes."
        >
          {!roles || roles.length === 0 ? (
            <EmptyState
              title="Using the shared mapping"
              description="This mandate has no client-specific account mapping; the all-clients mapping applies."
            />
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-xs tracking-wide text-muted uppercase">
                  <th scope="col" className="py-2">
                    Role
                  </th>
                  <th scope="col" className="py-2">
                    Account
                  </th>
                </tr>
              </thead>
              <tbody>
                {roles.map((role) => (
                  <tr key={role.role} className="border-b border-border last:border-0">
                    <td className="py-2">{humanise(role.role)}</td>
                    <td className="tnum py-2">{role.account_code}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>

      <Card
        title="Holdings"
        description="Balances come from the ledger, never from the holding record."
        bodyClassName="px-0 py-0"
        actions={<ButtonLink href={`/holdings?client=${id}`}>Open holdings</ButtonLink>}
      >
        {holdings.length === 0 ? (
          <div className="p-5">
            <EmptyState title="Nothing held" />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-ground">
                <tr className="text-xs tracking-wide text-muted uppercase">
                  <th scope="col" className="px-5 py-2">
                    Deal
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Counterparty
                  </th>
                  <th scope="col" className="px-3 py-2 text-right">
                    Outstanding
                  </th>
                  <th scope="col" className="px-3 py-2 text-right">
                    Accrued
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
                {holdings.map(({ holding, balances }) => (
                  <tr key={holding.id} className="border-t border-border">
                    <td className="px-5 py-2.5">
                      <Link
                        href={`/holdings/${encodeURIComponent(holding.id)}`}
                        className="font-medium text-accent underline"
                      >
                        {holding.id}
                      </Link>
                      <p className="text-xs text-muted">{humanise(holding.asset_class)}</p>
                    </td>
                    <td className="px-3 py-2.5 text-muted">{holding.counterparty}</td>
                    <td className="px-3 py-2.5 text-right">
                      <Money amount={balances.outstanding} currency={holding.currency} />
                    </td>
                    <td className="px-3 py-2.5 text-right">
                      <Money amount={balances.accrued_profit} muteZero />
                    </td>
                    <td className="px-3 py-2.5 text-muted">
                      {formatDate(holding.maturity_date)}
                    </td>
                    <td className="px-5 py-2.5">
                      <StatusPill state={holding.status} />
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
