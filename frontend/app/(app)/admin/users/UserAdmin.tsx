"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { FormRow, Label, Select, TextInput } from "@/components/forms/fields";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { StatusPill } from "@/components/ui/StatusPill";
import { Button, Card, ErrorBanner } from "@/components/ui/primitives";
import { apiSend } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import type { ClientRow, UserRole, UserRow } from "@/lib/api/schema";
import type { components } from "@/types/api";
import { ROLE_LABEL } from "@/lib/auth/permissions";
import { formatDateTime } from "@/lib/format";

const ROLES: UserRole[] = ["MAKER", "SIGNATORY", "FINANCE", "COMPLIANCE", "ADMIN"];

type CreateUserResponse = components["schemas"]["CreateUserResponse"];
type CreatedUser = { id: string; temporary_password: string };

/**
 * User administration.
 *
 * An administrator has no money powers at all: they create and disable accounts and
 * nothing else. A new account gets a temporary password, shown once here, which the
 * user must change at first sign-in.
 */
export function UserAdmin({ users, clients }: { users: UserRow[]; clients: ClientRow[] }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<CreatedUser | null>(null);
  const [busy, setBusy] = useState(false);
  const [dialog, setDialog] = useState<{ kind: string; user: UserRow } | null>(null);

  async function create(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const access = form.getAll("client_access").map(String).filter(Boolean);
    setBusy(true);
    setError(null);
    setCreated(null);
    try {
      const result = await apiSend<CreateUserResponse>("/users", {
        method: "POST",
        body: {
          id: String(form.get("id") ?? "").trim(),
          name: String(form.get("name") ?? "").trim(),
          title: String(form.get("title") ?? "").trim() || undefined,
          email: String(form.get("email") ?? "").trim(),
          role: String(form.get("role") ?? "MAKER"),
          client_access: access,
        },
      });
      setCreated({ id: result.user.id, temporary_password: result.temporary_password });
      event.currentTarget.reset();
      router.refresh();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  async function act(user: UserRow, path: string) {
    setError(null);
    try {
      const result = await apiSend<Partial<CreateUserResponse>>(
        `/users/${encodeURIComponent(user.id)}/${path}`,
        { method: "POST", body: {} },
      );
      if (result?.temporary_password) {
        setCreated({ id: user.id, temporary_password: result.temporary_password });
      }
      router.refresh();
    } catch (caught) {
      setError(errorMessage(caught));
      throw caught;
    }
  }

  return (
    <div className="space-y-6">
      {error && <ErrorBanner message={error} />}

      {created && (
        <Card title="Temporary password">
          <p className="text-sm text-ink">
            For <span className="font-medium">{created.id}</span>. This is shown once and
            cannot be retrieved again. Give it to the user by a channel other than
            email, and they must change it when they first sign in.
          </p>
          <p className="tnum mt-3 rounded-lg bg-ground px-4 py-3 font-mono text-sm break-all">
            {created.temporary_password}
          </p>
          <Button
            variant="secondary"
            type="button"
            className="mt-3 px-3 py-1.5"
            onClick={() => setCreated(null)}
          >
            I have passed it on
          </Button>
        </Card>
      )}

      <Card
        title="Create a user"
        description="Administrators manage accounts only. No role granted here lets an administrator move money."
      >
        <form onSubmit={create} className="space-y-4">
          <FormRow cols={3}>
            <Label label="Username" hint="Used to sign in." required>
              <TextInput name="id" required autoComplete="off" />
            </Label>
            <Label label="Full name" required>
              <TextInput name="name" required />
            </Label>
            <Label label="Job title" hint="Printed on instruction letters they sign.">
              <TextInput name="title" />
            </Label>
          </FormRow>

          <FormRow cols={2}>
            <Label label="Email" required>
              <TextInput name="email" type="email" required />
            </Label>
            <Label label="Role" required>
              <Select name="role" defaultValue="MAKER" required>
                {ROLES.map((role) => (
                  <option key={role} value={role}>
                    {ROLE_LABEL[role]}
                  </option>
                ))}
              </Select>
            </Label>
          </FormRow>

          <fieldset>
            <legend className="text-sm font-medium text-ink">
              Restrict to named clients
            </legend>
            <p className="mt-0.5 text-xs text-muted">
              Leave every box clear for access to all mandates. Restricting a user
              applies to every read and write (Conduct of Business reg 15).
            </p>
            <div className="mt-2 flex flex-wrap gap-3">
              {clients.map((client) => (
                <label key={client.id} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    name="client_access"
                    value={client.id}
                    className="size-4"
                  />
                  {client.legal_name}
                </label>
              ))}
            </div>
          </fieldset>

          <Button type="submit" disabled={busy}>
            {busy ? "Creating…" : "Create the user"}
          </Button>
        </form>
      </Card>

      <Card title={`Users (${users.length})`} bodyClassName="px-0 py-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-ground">
              <tr className="text-xs tracking-wide text-muted uppercase">
                <th scope="col" className="px-5 py-2">
                  User
                </th>
                <th scope="col" className="px-3 py-2">
                  Role
                </th>
                <th scope="col" className="px-3 py-2">
                  MFA
                </th>
                <th scope="col" className="px-3 py-2">
                  Client access
                </th>
                <th scope="col" className="px-3 py-2">
                  Last sign-in
                </th>
                <th scope="col" className="px-5 py-2">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <tr key={user.id} className="border-t border-border align-top">
                  <td className="px-5 py-3">
                    <p className="font-medium">{user.name}</p>
                    <p className="text-xs text-muted">
                      {user.id} · {user.email}
                    </p>
                    {user.title && <p className="text-xs text-muted">{user.title}</p>}
                  </td>
                  <td className="px-3 py-3">{ROLE_LABEL[user.role]}</td>
                  <td className="px-3 py-3">
                    <StatusPill
                      state={user.mfa_enrolled ? "DONE" : "TODO"}
                      label={user.mfa_enrolled ? "Enrolled" : "Not enrolled"}
                    />
                  </td>
                  <td className="px-3 py-3 text-muted">
                    {!user.client_access || user.client_access.length === 0
                      ? "all mandates"
                      : user.client_access.join(", ")}
                  </td>
                  <td className="px-3 py-3 text-muted">
                    {formatDateTime(user.last_login)}
                    {user.must_change_password && (
                      <p className="text-xs text-warning-ink">must change password</p>
                    )}
                  </td>
                  <td className="px-5 py-3">
                    <div className="flex flex-wrap gap-2">
                      <Button
                        variant="secondary"
                        type="button"
                        className="px-2.5 py-1 text-xs"
                        onClick={() => setDialog({ kind: "reset-password", user })}
                      >
                        Reset password
                      </Button>
                      <Button
                        variant="secondary"
                        type="button"
                        className="px-2.5 py-1 text-xs"
                        onClick={() => setDialog({ kind: "reset-mfa", user })}
                      >
                        Reset MFA
                      </Button>
                      <Button
                        variant={user.active ? "danger" : "secondary"}
                        type="button"
                        className="px-2.5 py-1 text-xs"
                        onClick={() =>
                          setDialog({ kind: user.active ? "disable" : "enable", user })
                        }
                      >
                        {user.active ? "Disable" : "Enable"}
                      </Button>
                    </div>
                    {!user.active && (
                      <p className="mt-1 text-xs text-danger-ink">disabled</p>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="border-t border-border px-5 py-3 text-xs text-muted">
          Accounts are never deleted: business records are kept for at least seven
          years, so a user who leaves is disabled instead.
        </p>
      </Card>

      <ConfirmDialog
        open={dialog !== null}
        title={
          dialog
            ? {
                "reset-password": `Reset the password for ${dialog.user.name}`,
                "reset-mfa": `Reset MFA for ${dialog.user.name}`,
                disable: `Disable ${dialog.user.name}`,
                enable: `Enable ${dialog.user.name}`,
              }[dialog.kind] ?? "Confirm"
            : "Confirm"
        }
        variant={dialog?.kind === "disable" ? "danger" : "primary"}
        confirmLabel="Do it"
        summary={
          dialog ? (
            <dl className="space-y-1">
              <div className="flex justify-between gap-4">
                <dt className="text-muted">User</dt>
                <dd className="font-medium">
                  {dialog.user.name} ({dialog.user.id})
                </dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-muted">Role</dt>
                <dd className="font-medium">{ROLE_LABEL[dialog.user.role]}</dd>
              </div>
              {dialog.kind === "disable" && (
                <p className="pt-2 text-xs text-muted">
                  Their existing sign-in tokens are revoked immediately. Any instruction
                  they have already signed keeps their signature on the record.
                </p>
              )}
              {dialog.kind === "reset-mfa" && (
                <p className="pt-2 text-xs text-muted">
                  They will be asked to enrol a new authenticator the next time they
                  sign in.
                </p>
              )}
            </dl>
          ) : null
        }
        onConfirm={async () => {
          if (!dialog) return;
          await act(dialog.user, dialog.kind);
        }}
        onClose={() => setDialog(null)}
      />
    </div>
  );
}
