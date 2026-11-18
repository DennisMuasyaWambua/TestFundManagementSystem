import type { Metadata } from "next";

import { UserAdmin } from "@/app/(app)/admin/users/UserAdmin";
import { Banner, PageHeader } from "@/components/ui/primitives";
import { apiFetch } from "@/lib/api/server";
import type { ClientRow, UserRow } from "@/lib/api/schema";

export const metadata: Metadata = { title: "Users" };

export default async function UsersPage() {
  const [users, clients] = await Promise.all([
    apiFetch<UserRow[]>("/users"),
    apiFetch<ClientRow[]>("/clients"),
  ]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Users"
        description="Accounts, roles and per-client access. Administrators have no authority over money."
      />

      <Banner tone="info" title="Which roles must use an authenticator">
        Multi-factor authentication is mandatory for signatories, finance and
        administrators. A user in one of those roles is asked to enrol an authenticator
        the first time they sign in, and cannot approve anything until they have.
      </Banner>

      <UserAdmin users={users} clients={clients} />
    </div>
  );
}
