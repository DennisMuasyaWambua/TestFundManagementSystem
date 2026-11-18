import type { Metadata } from "next";

import { ProfileForms } from "@/app/(app)/settings/profile/ProfileForms";
import { Card, Field, FieldList, PageHeader } from "@/components/ui/primitives";
import { requireUser } from "@/lib/auth/me";
import { ROLE_LABEL } from "@/lib/auth/permissions";
import { humanise } from "@/lib/format";

export const metadata: Metadata = { title: "My profile" };

export default async function ProfilePage({
  searchParams,
}: {
  searchParams: Promise<{ change?: string }>;
}) {
  const me = await requireUser();
  const { change } = await searchParams;

  return (
    <div className="space-y-6">
      <PageHeader title="My profile" description="Your account, password and authenticator." />

      <Card title="Your account">
        <FieldList cols={3}>
          <Field label="Name">{me.name}</Field>
          <Field label="Username">{me.id}</Field>
          <Field label="Email">{me.email}</Field>
          <Field label="Job title">{me.title}</Field>
          <Field label="Role">{ROLE_LABEL[me.role]}</Field>
          <Field label="Client access">
            {!me.client_access || me.client_access.length === 0
              ? "all mandates"
              : me.client_access.join(", ")}
          </Field>
        </FieldList>
      </Card>

      <ProfileForms me={me} mustChangePassword={change === "1" || me.must_change_password} />

      <Card
        title="What you may do"
        description="Enforced by the API on every request, not by the screens."
      >
        <ul className="grid grid-cols-1 gap-2 text-sm sm:grid-cols-2">
          {me.permissions.map((permission) => (
            <li key={permission} className="flex items-center gap-2">
              <span aria-hidden="true" className="text-success-ink">
                ✓
              </span>
              {humanise(permission)}
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
