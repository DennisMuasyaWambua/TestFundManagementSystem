import type { Metadata } from "next";

import { MigrationWizard } from "@/app/(app)/migration/MigrationWizard";
import { EmptyState, PageHeader } from "@/components/ui/primitives";
import { apiFetch } from "@/lib/api/server";
import type { BatchRow, ClientRow } from "@/lib/api/schema";

export const metadata: Metadata = { title: "New opening balance batch" };

export default async function NewMigrationPage() {
  const [clients, batches] = await Promise.all([
    apiFetch<ClientRow[]>("/clients"),
    apiFetch<BatchRow[]>("/opening-balances"),
  ]);

  // A client's opening balances are loaded once. Offering a second batch for a client
  // that already has one posted or in flight would only produce a rejection.
  const taken = new Set(
    batches
      .filter((batch) => batch.status !== "REJECTED")
      .map((batch) => batch.client_id),
  );
  const available = clients.filter((client) => !taken.has(client.id));

  return (
    <div className="space-y-6">
      <PageHeader
        title="Load a client's opening balances"
        description="What the client already holds, as at close of business on the cutover date. Every later workflow builds on these figures."
      />

      {available.length === 0 ? (
        <EmptyState
          title="Every mandate already has a batch"
          description="A posted batch can only be undone by a reversal batch, approved the same way."
        />
      ) : (
        <MigrationWizard clients={available} />
      )}
    </div>
  );
}
