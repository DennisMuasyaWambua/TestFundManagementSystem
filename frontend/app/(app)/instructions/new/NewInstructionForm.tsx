"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import {
  DateInput,
  FormRow,
  Label,
  MoneyInput,
  RateInput,
  Select,
  TextArea,
  TextInput,
} from "@/components/forms/fields";
import { Money } from "@/components/money/Money";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { StatusPill } from "@/components/ui/StatusPill";
import { Button, Card, ErrorBanner } from "@/components/ui/primitives";
import { apiGet, apiSend, newIdempotencyKey } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import type {
  CashPositionRow,
  CheckRow,
  ClientRow,
  CustodyAccountRow,
  InstructionRow,
  InstructionType,
} from "@/lib/api/schema";
import { formatMoney } from "@/lib/money";
import {
  INSTRUCTION_TYPE_LABEL,
  isInvestment,
  needsClientRequest,
} from "@/lib/instructions";

const TYPES = Object.keys(INSTRUCTION_TYPE_LABEL) as InstructionType[];

/**
 * Raising a custody instruction.
 *
 * The checks panel on the right is the API's own answer, re-asked every time the
 * form changes: the same `gate_checks` the API runs when it creates the instruction.
 * That way the maker sees why something is blocked -- insufficient cash, KYC not
 * approved, no custody appointment on file -- before submitting, and the screen can
 * never claim a check passes when the API thinks otherwise.
 */
export function NewInstructionForm({
  clients,
  custodyByClient,
}: {
  clients: ClientRow[];
  custodyByClient: Record<string, CustodyAccountRow[]>;
}) {
  const router = useRouter();

  const [clientId, setClientId] = useState(clients[0]?.id ?? "");
  const [type, setType] = useState<InstructionType>("PLACE_WAKALA");
  const [custodyAccountId, setCustodyAccountId] = useState(
    custodyByClient[clients[0]?.id ?? ""]?.[0]?.id ?? "",
  );
  const [amount, setAmount] = useState("");
  const [valueDate, setValueDate] = useState("");
  const [beneficiary, setBeneficiary] = useState("");
  const [beneficiaryAccount, setBeneficiaryAccount] = useState("");
  const [clientRequestRef, setClientRequestRef] = useState("");
  const [narrative, setNarrative] = useState("");
  const [deal, setDeal] = useState<Record<string, string>>({});

  const [checks, setChecks] = useState<CheckRow[] | null>(null);
  const [checksError, setChecksError] = useState<string | null>(null);
  const [cash, setCash] = useState<CashPositionRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);

  const accounts = custodyByClient[clientId] ?? [];
  const account = accounts.find((candidate) => candidate.id === custodyAccountId) ?? accounts[0];
  const currency = account?.currency ?? "USD";
  const position = cash?.find((row) => row.custody_account_id === custodyAccountId);

  // Keep the custody account consistent with the chosen client.
  useEffect(() => {
    const first = (custodyByClient[clientId] ?? [])[0];
    if (first && !(custodyByClient[clientId] ?? []).some((a) => a.id === custodyAccountId)) {
      setCustodyAccountId(first.id);
    }
  }, [clientId, custodyAccountId, custodyByClient]);

  // The cash position for this mandate: ledger balance less everything already
  // committed to instructions in flight.
  useEffect(() => {
    if (!clientId) return;
    let live = true;
    apiGet<CashPositionRow[]>(`/instructions/cash-position?client=${encodeURIComponent(clientId)}`)
      .then((rows) => {
        if (live) setCash(rows);
      })
      .catch(() => {
        if (live) setCash(null);
      });
    return () => {
      live = false;
    };
  }, [clientId]);

  // Re-run the gate checks whenever anything that feeds them changes.
  useEffect(() => {
    if (!clientId || !custodyAccountId || !amount || !valueDate) {
      setChecks(null);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void (async () => {
        try {
          const result = await apiSend<CheckRow[]>("/instructions/checks", {
            method: "POST",
            body: {
              client_id: clientId,
              custody_account_id: custodyAccountId,
              type,
              amount,
              value_date: valueDate,
              beneficiary: beneficiary || undefined,
              client_instruction_ref: clientRequestRef || null,
              params: deal,
            },
          });
          setChecks(result);
          setChecksError(null);
        } catch (caught) {
          setChecks(null);
          setChecksError(errorMessage(caught));
        }
      })();
    }, 350);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [clientId, custodyAccountId, type, amount, valueDate, beneficiary, clientRequestRef, deal]);

  const blocked = (checks ?? []).some((check) => !check.passed);
  const ready = Boolean(clientId && custodyAccountId && amount && valueDate && beneficiary);

  function setDealField(key: string, value: string) {
    setDeal((previous) => ({ ...previous, [key]: value }));
  }

  async function submit() {
    const created = await apiSend<InstructionRow>("/instructions", {
      method: "POST",
      idempotencyKey: newIdempotencyKey(),
      body: {
        client_id: clientId,
        custody_account_id: custodyAccountId,
        type,
        amount,
        value_date: valueDate,
        beneficiary,
        beneficiary_account: beneficiaryAccount || undefined,
        client_instruction_ref: clientRequestRef || null,
        narrative: narrative || undefined,
        params: deal,
      },
    });
    router.push(`/instructions/${created.id}`);
  }

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
      <div className="space-y-6 lg:col-span-2">
        <Card title="What is being instructed">
          <div className="space-y-4">
            <FormRow>
              <Label label="Instruction type" required>
                <Select
                  value={type}
                  onChange={(event) => {
                    setType(event.target.value as InstructionType);
                    setDeal({});
                  }}
                >
                  {TYPES.map((candidate) => (
                    <option key={candidate} value={candidate}>
                      {INSTRUCTION_TYPE_LABEL[candidate]}
                    </option>
                  ))}
                </Select>
              </Label>
              <Label label="Client" required>
                <Select value={clientId} onChange={(event) => setClientId(event.target.value)}>
                  {clients.map((client) => (
                    <option key={client.id} value={client.id}>
                      {client.legal_name}
                    </option>
                  ))}
                </Select>
              </Label>
            </FormRow>

            <FormRow>
              <Label
                label="Custody account to debit"
                hint="The currency of the instruction follows this account."
                required
              >
                <Select
                  value={custodyAccountId}
                  onChange={(event) => setCustodyAccountId(event.target.value)}
                >
                  {accounts.map((candidate) => (
                    <option key={candidate.id} value={candidate.id}>
                      {candidate.custodian} · {candidate.account_number} ({candidate.currency})
                    </option>
                  ))}
                </Select>
              </Label>
              <Label label={`Amount (${currency})`} required>
                <MoneyInput value={amount} onChange={(event) => setAmount(event.target.value)} />
              </Label>
            </FormRow>

            <FormRow>
              <Label label="Value date" required>
                <DateInput
                  value={valueDate}
                  onChange={(event) => setValueDate(event.target.value)}
                />
              </Label>
              <Label label="Beneficiary" required>
                <TextInput
                  value={beneficiary}
                  onChange={(event) => setBeneficiary(event.target.value)}
                  placeholder="Who the custodian pays"
                />
              </Label>
            </FormRow>

            <Label label="Beneficiary account details">
              <TextInput
                value={beneficiaryAccount}
                onChange={(event) => setBeneficiaryAccount(event.target.value)}
                placeholder="Bank, account number, SWIFT"
              />
            </Label>

            {needsClientRequest(type) && (
              <Label
                label="The client's written request reference"
                hint="A payout to the client may only be made on the client's own written instruction (CoB reg 30(2))."
                required
              >
                <TextInput
                  value={clientRequestRef}
                  onChange={(event) => setClientRequestRef(event.target.value)}
                />
              </Label>
            )}

            <Label label="Narrative">
              <TextArea
                value={narrative}
                onChange={(event) => setNarrative(event.target.value)}
                placeholder="Anything the custodian needs to know"
              />
            </Label>
          </div>
        </Card>

        {isInvestment(type) && (
          <Card
            title="Deal terms"
            description="These create the holding, and are printed on the letter."
          >
            <div className="space-y-4">
              <FormRow>
                <Label label="Deal reference" required>
                  <TextInput
                    value={deal.holding_id ?? ""}
                    onChange={(event) => setDealField("holding_id", event.target.value)}
                    placeholder="FD-R-08"
                  />
                </Label>
                <Label label="Counterparty" required>
                  <TextInput
                    value={deal.counterparty ?? ""}
                    onChange={(event) => setDealField("counterparty", event.target.value)}
                  />
                </Label>
              </FormRow>

              {(type === "PLACE_WAKALA" || type === "BUY_SUKUK" || type === "DISBURSE_FINANCING") && (
                <FormRow cols={3}>
                  <Label label="Expected profit rate" hint="As a decimal: 0.0425 is 4.25%." required>
                    <RateInput
                      value={deal.profit_rate ?? ""}
                      onChange={(event) => setDealField("profit_rate", event.target.value)}
                    />
                  </Label>
                  <Label label="Day basis">
                    <Select
                      value={deal.day_basis ?? "365"}
                      onChange={(event) => setDealField("day_basis", event.target.value)}
                    >
                      <option value="365">365</option>
                      <option value="360">360</option>
                    </Select>
                  </Label>
                  <Label label="Maturity date" required>
                    <DateInput
                      value={deal.maturity_date ?? ""}
                      onChange={(event) => setDealField("maturity_date", event.target.value)}
                    />
                  </Label>
                </FormRow>
              )}

              {type === "BUY_SUKUK" && (
                <Label
                  label="Nominal (face) value"
                  hint="Profit is paid on the nominal, which may differ from what is paid for the certificate."
                  required
                >
                  <MoneyInput
                    value={deal.nominal ?? ""}
                    onChange={(event) => setDealField("nominal", event.target.value)}
                  />
                </Label>
              )}

              {type === "PURCHASE_PROPERTY" && (
                <Label label="Monthly rent" required>
                  <MoneyInput
                    value={deal.monthly_rent ?? ""}
                    onChange={(event) => setDealField("monthly_rent", event.target.value)}
                  />
                </Label>
              )}

              <FormRow>
                <Label
                  label="Shariah approval reference"
                  hint="Every investment needs the Shariah board's approval on file."
                  required
                >
                  <TextInput
                    value={deal.shariah_cert_ref ?? ""}
                    onChange={(event) => setDealField("shariah_cert_ref", event.target.value)}
                  />
                </Label>
                <Label label="Counterparty's own reference">
                  <TextInput
                    value={deal.external_ref ?? ""}
                    onChange={(event) => setDealField("external_ref", event.target.value)}
                  />
                </Label>
              </FormRow>
            </div>
          </Card>
        )}

        {type === "FX_CONVERSION" && (
          <Card title="Conversion" description="Both accounts must belong to this same client.">
            <div className="space-y-4">
              <Label label="Custody account to receive the money" required>
                <Select
                  value={deal.target_custody_account_id ?? ""}
                  onChange={(event) =>
                    setDealField("target_custody_account_id", event.target.value)
                  }
                >
                  <option value="">Choose an account</option>
                  {accounts
                    .filter((candidate) => candidate.id !== custodyAccountId)
                    .map((candidate) => (
                      <option key={candidate.id} value={candidate.id}>
                        {candidate.custodian} · {candidate.account_number} ({candidate.currency})
                      </option>
                    ))}
                </Select>
              </Label>
              <FormRow>
                <Label label="Amount to be received" required>
                  <MoneyInput
                    value={deal.buy_amount ?? ""}
                    onChange={(event) => setDealField("buy_amount", event.target.value)}
                  />
                </Label>
                <Label label="Agreed rate" required>
                  <RateInput
                    value={deal.agreed_rate ?? ""}
                    onChange={(event) => setDealField("agreed_rate", event.target.value)}
                  />
                </Label>
              </FormRow>
            </div>
          </Card>
        )}
      </div>

      <div className="space-y-6">
        <Card title="Cash available" description="Ledger balance less everything in flight.">
          {position ? (
            <dl className="space-y-2 text-sm">
              <div className="flex justify-between gap-3">
                <dt className="text-muted">Ledger balance</dt>
                <dd>
                  <Money amount={position.ledger} currency={position.currency} />
                </dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-muted">Committed to instructions</dt>
                <dd>
                  <Money amount={position.committed} />
                </dd>
              </div>
              <div className="flex justify-between gap-3 border-t border-border pt-2 font-medium">
                <dt>Available</dt>
                <dd>
                  <Money amount={position.available} currency={position.currency} />
                </dd>
              </div>
            </dl>
          ) : (
            <p className="text-sm text-muted">Choose a client to see its cash position.</p>
          )}
        </Card>

        <Card title="Checks" description="Run by the API, not by this screen.">
          {checksError && <ErrorBanner message={checksError} />}
          {!checks && !checksError && (
            <p className="text-sm text-muted">
              Fill in the client, the account, the amount and the value date, and the
              checks will run.
            </p>
          )}
          {checks && (
            <ul className="divide-y divide-border">
              {checks.map((check) => (
                <li key={check.key} className="flex items-start gap-3 py-2.5">
                  <StatusPill
                    state={check.passed ? "DONE" : "BLOCKED"}
                    label={check.passed ? "Pass" : "Fail"}
                  />
                  <div className="min-w-0">
                    <p className="text-sm text-ink">{check.label}</p>
                    {check.detail && <p className="text-xs text-muted">{check.detail}</p>}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        {error && <ErrorBanner message={error} />}

        <Button
          type="button"
          className="w-full"
          disabled={!ready || blocked}
          onClick={() => setConfirming(true)}
        >
          {blocked ? "Checks must pass first" : "Raise the instruction"}
        </Button>
        <p className="text-xs text-muted">
          Raising it does not move money. It goes to two authorised signatories, and the
          movement is booked only once the custodian confirms it.
        </p>
      </div>

      <ConfirmDialog
        open={confirming}
        title="Raise this custody instruction"
        confirmLabel="Raise it"
        summary={
          <dl className="space-y-1">
            <SummaryRow
              label="Client"
              value={clients.find((c) => c.id === clientId)?.legal_name ?? clientId}
            />
            <SummaryRow label="Instruction" value={INSTRUCTION_TYPE_LABEL[type]} />
            <SummaryRow
              label="Debit account"
              value={
                account ? `${account.custodian} · ${account.account_number}` : custodyAccountId
              }
            />
            <SummaryRow label="Amount" value={formatMoney(amount, { currency })} />
            <SummaryRow label="Value date" value={valueDate} />
            <SummaryRow label="Beneficiary" value={beneficiary} />
          </dl>
        }
        onConfirm={async () => {
          setError(null);
          try {
            await submit();
          } catch (caught) {
            setError(errorMessage(caught));
            throw caught;
          }
        }}
        onClose={() => setConfirming(false)}
      />
    </div>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="text-muted">{label}</dt>
      <dd className="text-right font-medium">{value}</dd>
    </div>
  );
}
