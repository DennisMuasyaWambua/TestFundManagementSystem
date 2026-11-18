"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { DateInput, FormRow, Label, MoneyInput, Select, TextInput } from "@/components/forms/fields";
import { Money } from "@/components/money/Money";
import { StatusPill } from "@/components/ui/StatusPill";
import { Button, Card, EmptyState, ErrorBanner } from "@/components/ui/primitives";
import { apiSend, newIdempotencyKey } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import type {
  ClientRow,
  CustodyAccountRow,
  HoldingListRow,
  ReconResponse,
} from "@/lib/api/schema";
import { formatDate } from "@/lib/format";

/**
 * Keying the custodian's figures, and running the reconciliation against them.
 *
 * A reconciliation may never be run by a payment signatory (CoB reg 29(5)-(7)), and
 * the API refuses it for that role; this screen is only reachable by finance and
 * compliance. Who ran it and when is stored on the run itself.
 */
export function ReconciliationPanel({
  clients,
  custodyAccounts,
  holdings,
  asOf,
}: {
  clients: ClientRow[];
  custodyAccounts: CustodyAccountRow[];
  holdings: HoldingListRow[];
  asOf: string;
}) {
  const router = useRouter();
  const [result, setResult] = useState<ReconResponse | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [clientId, setClientId] = useState("");

  async function recordBalance(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy("balance");
    setError(null);
    setSaved(null);
    try {
      await apiSend("/custodian-balances", {
        method: "POST",
        idempotencyKey: newIdempotencyKey(),
        body: {
          custody_account_id: String(form.get("custody_account_id") ?? ""),
          as_of: String(form.get("as_of") ?? ""),
          balance: String(form.get("balance") ?? "").trim(),
          statement_ref: String(form.get("statement_ref") ?? "").trim(),
        },
      });
      setSaved("Cash balance recorded from the statement.");
      event.currentTarget.reset();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(null);
    }
  }

  async function recordPosition(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy("position");
    setError(null);
    setSaved(null);
    try {
      await apiSend("/custodian-positions", {
        method: "POST",
        idempotencyKey: newIdempotencyKey(),
        body: {
          holding_id: String(form.get("holding_id") ?? ""),
          as_of: String(form.get("as_of") ?? ""),
          amount: String(form.get("amount") ?? "").trim(),
          statement_ref: String(form.get("statement_ref") ?? "").trim(),
        },
      });
      setSaved("Position recorded from the custodian's report.");
      event.currentTarget.reset();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(null);
    }
  }

  async function run() {
    setBusy("run");
    setError(null);
    setSaved(null);
    try {
      const outcome = await apiSend<ReconResponse>("/reconciliations", {
        method: "POST",
        idempotencyKey: newIdempotencyKey(),
        body: { as_of: asOf, client_id: clientId || null, scope: "BOTH" },
      });
      setResult(outcome);
      router.refresh();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-6">
      {error && <ErrorBanner message={error} />}
      {saved && (
        <p className="rounded-lg bg-success-tint px-4 py-3 text-sm text-success-ink">{saved}</p>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card
          title="Record a cash balance"
          description="The custodian's own closing balance for one custody account."
        >
          <form onSubmit={recordBalance} className="space-y-4">
            <Label label="Custody account" required>
              <Select name="custody_account_id" required>
                {custodyAccounts.map((account) => (
                  <option key={account.id} value={account.id}>
                    {account.client_id} · {account.custodian} · {account.account_number} (
                    {account.currency})
                  </option>
                ))}
              </Select>
            </Label>
            <FormRow cols={3}>
              <Label label="As at" required>
                <DateInput name="as_of" defaultValue={asOf} required />
              </Label>
              <Label label="Balance" required>
                <MoneyInput name="balance" required />
              </Label>
              <Label label="Statement reference" required>
                <TextInput name="statement_ref" required />
              </Label>
            </FormRow>
            <Button type="submit" disabled={busy !== null}>
              {busy === "balance" ? "Saving…" : "Record it"}
            </Button>
          </form>
        </Card>

        <Card
          title="Record a position"
          description="What the custodian reports holding for one deal. Sukuk are compared on nominal."
        >
          <form onSubmit={recordPosition} className="space-y-4">
            <Label label="Deal" required>
              <Select name="holding_id" required>
                {holdings.map(({ holding }) => (
                  <option key={holding.id} value={holding.id}>
                    {holding.client_id} · {holding.id} · {holding.counterparty}
                  </option>
                ))}
              </Select>
            </Label>
            <FormRow cols={3}>
              <Label label="As at" required>
                <DateInput name="as_of" defaultValue={asOf} required />
              </Label>
              <Label label="Amount" required>
                <MoneyInput name="amount" required />
              </Label>
              <Label label="Statement reference" required>
                <TextInput name="statement_ref" required />
              </Label>
            </FormRow>
            <Button type="submit" disabled={busy !== null}>
              {busy === "position" ? "Saving…" : "Record it"}
            </Button>
          </form>
        </Card>
      </div>

      <Card
        title="Run the reconciliation"
        description="Cash daily, positions monthly. The run records who performed it and when."
      >
        <div className="flex flex-wrap items-end gap-3">
          <Label label="Client" className="w-full sm:w-72">
            <Select value={clientId} onChange={(event) => setClientId(event.target.value)}>
              <option value="">Every mandate</option>
              {clients.map((client) => (
                <option key={client.id} value={client.id}>
                  {client.legal_name}
                </option>
              ))}
            </Select>
          </Label>
          <Button type="button" onClick={run} disabled={busy !== null}>
            {busy === "run" ? "Running…" : `Reconcile as at ${formatDate(asOf)}`}
          </Button>
        </div>
      </Card>

      {result && (
        <Card
          title={
            result.breaks === 0
              ? "Reconciled with no breaks"
              : `${result.breaks} break${result.breaks === 1 ? "" : "s"}`
          }
          description={`As at ${formatDate(result.as_of)}${result.run_id ? ` · run #${result.run_id}` : ""}`}
          bodyClassName="px-0 py-0"
        >
          {result.lines.length === 0 ? (
            <div className="p-5">
              <EmptyState title="Nothing to compare" />
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-ground">
                  <tr className="text-xs tracking-wide text-muted uppercase">
                    <th scope="col" className="px-5 py-2">
                      What
                    </th>
                    <th scope="col" className="px-3 py-2">
                      Scope
                    </th>
                    <th scope="col" className="px-3 py-2 text-right">
                      Our ledger
                    </th>
                    <th scope="col" className="px-3 py-2 text-right">
                      The custodian
                    </th>
                    <th scope="col" className="px-3 py-2 text-right">
                      Difference
                    </th>
                    <th scope="col" className="px-5 py-2">
                      Outcome
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {result.lines.map((line) => (
                    <tr
                      key={`${line.scope}-${line.key}`}
                      className={line.matched ? "border-t border-border" : "border-t border-border bg-danger-tint/40"}
                    >
                      <td className="px-5 py-2.5">
                        <p className="font-medium">{line.label}</p>
                        <p className="text-xs text-muted">
                          {line.key}
                          {line.note ? ` · ${line.note}` : ""}
                        </p>
                      </td>
                      <td className="px-3 py-2.5 text-muted">{line.scope.toLowerCase()}</td>
                      <td className="px-3 py-2.5 text-right">
                        <Money amount={line.ledger} currency={line.currency} />
                      </td>
                      <td className="px-3 py-2.5 text-right">
                        {line.custodian === null || line.custodian === undefined ? (
                          <span className="text-muted">not supplied</span>
                        ) : (
                          <Money amount={line.custodian} />
                        )}
                      </td>
                      <td className="px-3 py-2.5 text-right">
                        <Money amount={line.difference} muteZero colour />
                      </td>
                      <td className="px-5 py-2.5">
                        <StatusPill state={line.matched ? "MATCHED" : "BREAK"} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
