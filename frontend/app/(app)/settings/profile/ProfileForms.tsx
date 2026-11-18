"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { FormRow, Label, TextInput } from "@/components/forms/fields";
import { Button, Card, ErrorBanner } from "@/components/ui/primitives";
import { apiSend } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import type { Me, MfaEnrolResponse } from "@/lib/api/schema";

/**
 * Changing a password, and enrolling an authenticator.
 *
 * Changing the password revokes every token already issued to this user, so anyone
 * holding a stolen one is signed out at once -- including this browser, which is why
 * the user is sent back to sign in afterwards.
 */
export function ProfileForms({
  me,
  mustChangePassword,
}: {
  me: Me;
  mustChangePassword: boolean;
}) {
  const router = useRouter();
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [passwordBusy, setPasswordBusy] = useState(false);

  const [secret, setSecret] = useState<MfaEnrolResponse | null>(null);
  const [mfaError, setMfaError] = useState<string | null>(null);
  const [mfaBusy, setMfaBusy] = useState(false);
  const [mfaDone, setMfaDone] = useState(false);

  async function changePassword(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const next = String(form.get("new_password") ?? "");
    if (next !== String(form.get("confirm_password") ?? "")) {
      setPasswordError("The two new passwords do not match.");
      return;
    }
    setPasswordBusy(true);
    setPasswordError(null);
    try {
      await apiSend("/auth/change-password", {
        method: "POST",
        body: {
          current_password: String(form.get("current_password") ?? ""),
          new_password: next,
        },
      });
      // Every token is now revoked, this one included.
      window.location.assign("/login");
    } catch (caught) {
      setPasswordError(errorMessage(caught));
      setPasswordBusy(false);
    }
  }

  async function startEnrolment() {
    setMfaBusy(true);
    setMfaError(null);
    try {
      setSecret(await apiSend<MfaEnrolResponse>("/auth/mfa/enroll", { method: "POST", body: {} }));
    } catch (caught) {
      setMfaError(errorMessage(caught));
    } finally {
      setMfaBusy(false);
    }
  }

  async function verifyEnrolment(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setMfaBusy(true);
    setMfaError(null);
    try {
      await apiSend("/auth/mfa/verify", {
        method: "POST",
        body: { code: String(form.get("code") ?? "").trim() },
      });
      setMfaDone(true);
      setSecret(null);
      router.refresh();
    } catch (caught) {
      setMfaError(errorMessage(caught));
    } finally {
      setMfaBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <Card
        title="Change your password"
        description="At least 12 characters, with an upper case letter, a lower case letter, a digit and a symbol."
      >
        {mustChangePassword && (
          <div className="mb-4 rounded-lg bg-warning-tint px-4 py-3 text-sm text-warning-ink">
            You are signed in with a temporary password. Change it before doing anything
            else.
          </div>
        )}

        <form onSubmit={changePassword} className="space-y-4">
          <Label label="Your current password" required>
            <TextInput
              name="current_password"
              type="password"
              autoComplete="current-password"
              required
            />
          </Label>
          <FormRow cols={2}>
            <Label label="New password" required>
              <TextInput
                name="new_password"
                type="password"
                autoComplete="new-password"
                minLength={12}
                required
              />
            </Label>
            <Label label="New password again" required>
              <TextInput
                name="confirm_password"
                type="password"
                autoComplete="new-password"
                minLength={12}
                required
              />
            </Label>
          </FormRow>

          {passwordError && <ErrorBanner message={passwordError} />}

          <p className="text-xs text-muted">
            Changing your password signs you out everywhere, including here.
          </p>

          <Button type="submit" disabled={passwordBusy}>
            {passwordBusy ? "Changing…" : "Change my password"}
          </Button>
        </form>
      </Card>

      <Card
        title="Authenticator app"
        description={
          me.mfa_enrolled
            ? "An authenticator is enrolled on this account."
            : "Scan the secret into an authenticator app, then confirm with the code it shows."
        }
      >
        {mfaDone && (
          <p className="mb-4 rounded-lg bg-success-tint px-4 py-3 text-sm text-success-ink">
            Enrolled. You will be asked for a code each time you sign in.
          </p>
        )}

        {me.mfa_enrolled && !secret && !mfaDone && (
          <p className="text-sm text-muted">
            To replace it, ask an administrator to reset your MFA first. The secret is
            shown only once, when it is created.
          </p>
        )}

        {!me.mfa_enrolled && !secret && (
          <>
            {mfaError && <ErrorBanner message={mfaError} />}
            <Button type="button" onClick={startEnrolment} disabled={mfaBusy} className="mt-2">
              {mfaBusy ? "Generating…" : "Start enrolment"}
            </Button>
          </>
        )}

        {secret && (
          <div className="space-y-4">
            <div className="rounded-lg bg-ground px-4 py-3">
              <p className="text-xs font-medium tracking-wide text-muted uppercase">
                Your secret — shown once only
              </p>
              <p className="tnum mt-1 font-mono text-sm break-all">{secret.secret}</p>
              <p className="mt-2 text-xs text-muted">
                Or add it by URI: <span className="break-all">{secret.provisioning_uri}</span>
              </p>
            </div>

            <form onSubmit={verifyEnrolment} className="space-y-4">
              <Label
                label="The six-digit code from your app"
                hint="This confirms the secret was stored correctly before it is relied on."
                required
              >
                <TextInput
                  name="code"
                  inputMode="numeric"
                  pattern="[0-9]{6}"
                  maxLength={6}
                  required
                  className="tnum tracking-[0.3em]"
                />
              </Label>

              {mfaError && <ErrorBanner message={mfaError} />}

              <Button type="submit" disabled={mfaBusy}>
                {mfaBusy ? "Verifying…" : "Confirm enrolment"}
              </Button>
            </form>
          </div>
        )}
      </Card>
    </div>
  );
}
