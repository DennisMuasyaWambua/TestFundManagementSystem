"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import {
  DateInput,
  FormRow,
  Label,
  MoneyInput,
  Select,
  TextArea,
  TextInput,
} from "@/components/forms/fields";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Button, Card, ErrorBanner } from "@/components/ui/primitives";
import { apiSend, newIdempotencyKey } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import type { ClientRow, CustodyAccountRow } from "@/lib/api/schema";
import { formatMoney } from "@/lib/money";

/**
 * Money in from the client.
 *
 * No instruction letter is needed for a credit -- the custodian has already received
 * the money -- but the custodian's advice reference is mandatory, so the posting is
 * always traceable to the document that evidences it.
 */
export function ContributionForm({
  clients,
  custodyByClient,
}: {
  clients: ClientRow[];
  custodyByClient: Record<string, CustodyAccountRow[]>;
}) {
  const router = useRouter();
  const [clientId, setClientId] = useState(clients[0]?.id ?? "");
  const [custodyAccountId, setCustodyAccountId] = useState(
    custodyByClient[clients[0]?.id ?? ""]?.[0]?.id ?? "",
  );
  const [amount, setAmount] = useState("");
  const [valueDate, setValueDate] = useState("");
  const [adviceRef, setAdviceRef] = useState("");
  const [narrative, setNarrative] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const accounts = custodyByClient[clientId] ?? [];
  const account = accounts.find((candidate) => candidate.id === custodyAccountId) ?? accounts[0];
  const currency = account?.currency ?? "USD";

  const ready = Boolean(clientId && custodyAccountId && amount && valueDate && adviceRef);

  return (
    <Card
      title="A contribution from the client"
      description="This increases the client's capital. It is booked to the custody account the custodian credited."
    >
      <div className="space-y-4">
        <FormRow>
          <Label label="Client" required>
            <Select
              value={clientId}
              onChange={(event) => {
                setClientId(event.target.value);
                const first = custodyByClient[event.target.value]?.[0];
                if (first) setCustodyAccountId(first.id);
              }}
            >
              {clients.map((client) => (
                <option key={client.id} value={client.id}>
                  {client.legal_name}
                </option>
              ))}
            </Select>
          </Label>
          <Label label="Custody account credited" required>
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
        </FormRow>

        <FormRow cols={3}>
          <Label label={`Amount (${currency})`} required>
            <MoneyInput value={amount} onChange={(event) => setAmount(event.target.value)} />
          </Label>
          <Label label="Value date" required>
            <DateInput
              value={valueDate}
              onChange={(event) => setValueDate(event.target.value)}
            />
          </Label>
          <Label
            label="Custodian advice reference"
            hint="From the credit advice."
            required
          >
            <TextInput value={adviceRef} onChange={(event) => setAdviceRef(event.target.value)} />
          </Label>
        </FormRow>

        <Label label="Narrative">
          <TextArea value={narrative} onChange={(event) => setNarrative(event.target.value)} />
        </Label>

        {error && <ErrorBanner message={error} />}

        <div className="rounded-lg bg-ground px-4 py-3 text-sm">
          <p className="font-medium text-ink">What will be posted</p>
          <p className="mt-1 text-muted">
            Debit the custody cash account, credit the client&rsquo;s capital — the
            client&rsquo;s money is a liability of the firm, never its own asset.
          </p>
        </div>

        <Button type="button" disabled={!ready} onClick={() => setConfirming(true)}>
          Record the contribution
        </Button>
      </div>

      <ConfirmDialog
        open={confirming}
        title="Record this contribution"
        confirmLabel="Record it"
        summary={
          <dl className="space-y-1">
            <Row
              label="Client"
              value={clients.find((c) => c.id === clientId)?.legal_name ?? clientId}
            />
            <Row
              label="Account credited"
              value={account ? `${account.custodian} · ${account.account_number}` : custodyAccountId}
            />
            <Row label="Amount" value={formatMoney(amount, { currency })} />
            <Row label="Value date" value={valueDate} />
            <Row label="Advice reference" value={adviceRef} />
          </dl>
        }
        onConfirm={async () => {
          setError(null);
          try {
            await apiSend("/contributions", {
              method: "POST",
              idempotencyKey: newIdempotencyKey(),
              body: {
                client_id: clientId,
                custody_account_id: custodyAccountId,
                amount,
                value_date: valueDate,
                advice_ref: adviceRef,
                narrative: narrative || undefined,
              },
            });
            router.push(`/clients/${clientId}`);
          } catch (caught) {
            setError(errorMessage(caught));
            throw caught;
          }
        }}
        onClose={() => setConfirming(false)}
      />
    </Card>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="text-muted">{label}</dt>
      <dd className="text-right font-medium">{value}</dd>
    </div>
  );
}
