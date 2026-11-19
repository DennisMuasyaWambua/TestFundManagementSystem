import type { Metadata } from "next";

import { MigrationWizard } from "@/app/(app)/migration/MigrationWizard";
import { EmptyState, PageHeader } from "@/components/ui/primitives";
import { apiFetch } from "@/lib/api/server";
import type { ClientRow } from "@/lib/api/schema";

export const metadata: Metadata = { title: "New opening balance batch" };

export default async function NewMigrationPage() {
  const clients = await apiFetch<ClientRow[]>("/clients");

  // Every client is always offered here, including one that already has a batch
  // (draft, rejected, or even posted) -- this test system allows as many batches
  // per client as you want, for exploring the flow.

  return (
    <div className="space-y-6">
      <PageHeader
        title="Load a client's opening balances"
        description="What the client already holds, as at close of business on the cutover date. Every later workflow builds on these figures."
      />

      {clients.length === 0 ? (
        <EmptyState
          title="No clients yet"
          description="Create a client first, from the Clients screen."
        />
      ) : (
        <MigrationWizard clients={clients} />
      )}
    </div>
  );
}
