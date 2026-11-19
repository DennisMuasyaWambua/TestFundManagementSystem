import type { Metadata } from "next";
import Link from "next/link";

import { InstructionActions } from "@/app/(app)/instructions/[instructionId]/InstructionActions";
import { Money } from "@/components/money/Money";
import { StatusPill } from "@/components/ui/StatusPill";
import { Stepper } from "@/components/ui/Stepper";
import {
  Banner,
  Card,
  Field,
  FieldList,
  PageHeader,
} from "@/components/ui/primitives";
import { apiFetch } from "@/lib/api/server";
import type { InstructionDetail } from "@/lib/api/schema";
import { formatDate, formatDateTime, humanise } from "@/lib/format";
import { INSTRUCTION_TYPE_LABEL, lifecycleSteps } from "@/lib/instructions";

export const metadata: Metadata = { title: "Instruction" };

export default async function InstructionPage({
  params,
}: {
  params: Promise<{ instructionId: string }>;
}) {
  const { instructionId } = await params;
  const detail = await apiFetch<InstructionDetail>(`/instructions/${instructionId}`);
  const instruction = detail.instruction;
  const approvals = instruction.approvals ?? [];
  const params_ = (instruction.params ?? {}) as Record<string, unknown>;

  return (
    <div className="space-y-6">
      <PageHeader
        title={instruction.reference}
        description={INSTRUCTION_TYPE_LABEL[instruction.type] ?? humanise(instruction.type)}
        actions={<StatusPill state={instruction.status} />}
      />

      {instruction.status === "REJECTED" && instruction.rejection_reason && (
        <Banner tone="danger" title="Rejected">
          {instruction.rejection_reason}
        </Banner>
      )}

      {instruction.status === "SETTLED" && (
        <Banner tone="success" title="Settled and booked">
          The custodian confirmed this movement under reference{" "}
          <span className="font-medium">{instruction.custodian_confirmation_ref}</span> on{" "}
          {formatDate(instruction.settled_on)}.
          {instruction.journal_entry_id && (
            <>
              {" "}
              <Link
                href={`/journal?entry=${instruction.journal_entry_id}`}
                className="font-medium underline"
              >
                See the journal entry
              </Link>
              .
            </>
          )}
        </Banner>
      )}

      <Card title="Progress">
        <Stepper steps={lifecycleSteps(instruction.status, approvals.length)} />
      </Card>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card title="The instruction" className="lg:col-span-2">
          <FieldList cols={3}>
            <Field label="Client">
              <Link href={`/clients/${instruction.client_id}`} className="text-accent underline">
                {instruction.client_id}
              </Link>
            </Field>
            <Field label="Custody account">{instruction.custody_account_id}</Field>
            <Field label="Amount">
              <Money
                amount={instruction.amount}
                currency={instruction.currency}
                className="font-semibold"
              />
            </Field>
            <Field label="Value date">{formatDate(instruction.value_date)}</Field>
            <Field label="Beneficiary">{instruction.beneficiary}</Field>
            <Field label="Beneficiary account">{instruction.beneficiary_account || "—"}</Field>
            <Field label="Prepared by">{instruction.maker_id}</Field>
            {instruction.client_instruction_ref && (
              <Field label="Client's written request">
                {instruction.client_instruction_ref}
              </Field>
            )}
            {instruction.holding_id && (
              <Field label="Deal">
                <Link
                  href={`/holdings/${encodeURIComponent(instruction.holding_id)}`}
                  className="text-accent underline"
                >
                  {instruction.holding_id}
                </Link>
              </Field>
            )}
          </FieldList>

          {instruction.narrative && (
            <p className="mt-4 border-t border-border pt-4 text-sm text-muted">
              {instruction.narrative}
            </p>
          )}

          {Object.keys(params_).length > 0 && (
            <div className="mt-4 border-t border-border pt-4">
              <h3 className="text-xs font-semibold tracking-wide text-muted uppercase">
                Deal terms
              </h3>
              <dl className="mt-2 grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2">
                {Object.entries(params_).map(([key, value]) => (
                  <div key={key} className="flex justify-between gap-3 text-sm">
                    <dt className="text-muted">{humanise(key)}</dt>
                    <dd className="text-right font-medium">{String(value)}</dd>
                  </div>
                ))}
              </dl>
            </div>
          )}
        </Card>

        <div className="space-y-6">
          <Card
            title="Signatures"
            description="Two authorised signatures are required."
          >
            {approvals.length === 0 ? (
              <p className="text-sm text-muted">Not yet signed.</p>
            ) : (
              <ul className="space-y-3">
                {approvals.map((approval) => (
                  <li key={approval.user_id} className="text-sm">
                    <p className="font-medium text-ink">
                      {approval.user_name ?? approval.user_id}
                    </p>
                    <p className="text-xs text-muted">
                      {approval.title ?? "Authorised signatory"} ·{" "}
                      {formatDateTime(approval.approved_at)}
                    </p>
                  </li>
                ))}
              </ul>
            )}
            <p className="mt-3 border-t border-border pt-3 text-xs text-muted">
              {approvals.length} of 2 required signatures.
            </p>
          </Card>

          <Card title="Document trail">
            <FieldList cols={1}>
              <Field label="Letter hash (SHA-256)">
                <span className="font-mono text-xs break-all">
                  {instruction.letter_pdf_sha256 ?? "generated on approval"}
                </span>
              </Field>
              <Field label="Signed scan hash (SHA-256)">
                <span className="font-mono text-xs break-all">
                  {instruction.signed_copy_sha256 ?? "not uploaded yet"}
                </span>
              </Field>
              <Field label="Sent to custodian">{formatDateTime(instruction.sent_at)}</Field>
            </FieldList>
          </Card>
        </div>
      </div>

      {(detail.checks ?? []).length > 0 && (
        <Card
          title="Pre-release checks"
          description="Every one of these had to pass before the instruction could be raised."
        >
          <ul className="divide-y divide-border">
            {(detail.checks ?? []).map((check) => (
              <li key={check.key} className="flex items-start gap-3 py-2.5">
                <StatusPill
                  state={check.passed ? "DONE" : "BLOCKED"}
                  label={check.passed ? "Passed" : "Failed"}
                />
                <div className="min-w-0">
                  <p className="text-sm text-ink">{check.label}</p>
                  {check.detail && <p className="text-xs text-muted">{check.detail}</p>}
                </div>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card title="What happens next">
        <InstructionActions detail={detail} />
      </Card>
    </div>
  );
}
