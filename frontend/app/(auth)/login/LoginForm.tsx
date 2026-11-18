"use client";

import { useActionState } from "react";

import { login } from "@/app/(auth)/login/actions";
import { INITIAL_LOGIN_STATE } from "@/app/(auth)/login/state";
import { Label, TextInput } from "@/components/forms/fields";
import { Button, ErrorBanner } from "@/components/ui/primitives";

/**
 * Sign-in, in two steps.
 *
 * The one-time code field appears only once the API has said this role needs one
 * (`MFA_REQUIRED`), so a user whose role does not require MFA never sees it, and the
 * screen never has to guess from the username who needs it.
 */
export function LoginForm({ next }: { next: string }) {
  const [state, submit, pending] = useActionState(login, INITIAL_LOGIN_STATE);

  return (
    <form action={submit} className="space-y-4">
      <input type="hidden" name="next" value={next} />

      {state.error && (
        <ErrorBanner
          title={state.needsTotp ? "One more step" : "Could not sign you in"}
          message={state.error}
        />
      )}

      <Label label="Username" required>
        <TextInput
          name="username"
          autoComplete="username"
          defaultValue={state.username}
          required
          autoFocus={!state.needsTotp}
          readOnly={state.needsTotp}
        />
      </Label>

      <Label label="Password" required>
        <TextInput name="password" type="password" autoComplete="current-password" required />
      </Label>

      {state.needsTotp && (
        <Label
          label="Authenticator code"
          hint="The six-digit code from your authenticator app."
          required
        >
          <TextInput
            name="totp"
            inputMode="numeric"
            autoComplete="one-time-code"
            pattern="[0-9]{6}"
            maxLength={6}
            required
            autoFocus
            className="tnum tracking-[0.3em]"
          />
        </Label>
      )}

      <Button type="submit" disabled={pending} className="w-full">
        {pending ? "Signing in…" : state.needsTotp ? "Verify and sign in" : "Sign in"}
      </Button>

      <p className="text-xs text-muted">
        Five failed attempts lock the account for fifteen minutes. Every sign-in,
        failure and lockout is recorded in the audit log.
      </p>
    </form>
  );
}
