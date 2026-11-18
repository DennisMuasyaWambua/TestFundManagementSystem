import type { Metadata } from "next";

import { NewInstructionForm } from "@/app/(app)/instructions/new/NewInstructionForm";
import { Banner, EmptyState, PageHeader } from "@/components/ui/primitives";
import { apiFetch } from "@/lib/api/server";
import type { ClientRow, CustodyAccountRow } from "@/lib/api/schema";

export const metadata: Metadata = { title: "New instruction" };

export default async function NewInstructionPage() {
  const clients = await apiFetch<ClientRow[]>("/clients");

  // Only mandates that can actually be instructed: KYC approved, agreement on file,
  // custody appointment recorded.  The API refuses the rest anyway, and offering them
  // in the picker would only produce a form that cannot be submitted.
  const eligible = clients.filter(
    (client) => client.onboarding_gaps.length === 0 && client.status === "ACTIVE",
  );

  const custodyByClient: Record<string, CustodyAccountRow[]> = {};
  await Promise.all(
    eligible.map(async (client) => {
      custodyByClient[client.id] = await apiFetch<CustodyAccountRow[]>(
        `/clients/${encodeURIComponent(client.id)}/custody-accounts`,
      );
    }),
  );

  const blocked = clients.filter((client) => client.onboarding_gaps.length > 0);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Raise a custody instruction"
        description="The bank never moves money itself. This prepares a letter for the custodian, which two authorised signatories must sign."
      />

      {blocked.length > 0 && (
        <Banner tone="warning" title="Some mandates cannot be instructed yet">
          {blocked.map((client) => client.legal_name).join(", ")} —{" "}
          {blocked.length === 1 ? "this mandate" : "these mandates"} still
          {blocked.length === 1 ? " has" : " have"} onboarding gaps, so no instruction
          can be raised against{blocked.length === 1 ? " it" : " them"}.
        </Banner>
      )}

      {eligible.length === 0 ? (
        <EmptyState
          title="No mandate is ready to be instructed"
          description="A client needs an approved KYC record, a signed investment management agreement and a custody appointment on file before any money can move."
        />
      ) : (
        <NewInstructionForm clients={eligible} custodyByClient={custodyByClient} />
      )}
    </div>
  );
}
