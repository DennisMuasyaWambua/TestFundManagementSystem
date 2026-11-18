"use server";

/**
 * Signing in.
 *
 * The password and the one-time code are posted to this Server Action, which calls
 * the Python API and stores the token it returns in an httpOnly cookie.  The token
 * is never sent to the browser, so script on the page -- injected or otherwise --
 * has nothing to steal.
 */

import { redirect } from "next/navigation";

import { ApiError } from "@/lib/api/errors";
import { apiFetch } from "@/lib/api/server";
import type { LoginResponse } from "@/lib/api/schema";
import { endSession, startSession } from "@/lib/auth/session";

import type { LoginState } from "./state";

function safeNext(value: FormDataEntryValue | null): string {
  const next = typeof value === "string" ? value : "";
  // Only same-site paths: an open redirect here would be a phishing vector.
  return next.startsWith("/") && !next.startsWith("//") ? next : "/dashboard";
}

export async function login(previous: LoginState, form: FormData): Promise<LoginState> {
  const username = String(form.get("username") ?? "").trim();
  const password = String(form.get("password") ?? "");
  const totp = String(form.get("totp") ?? "").trim();
  const next = safeNext(form.get("next"));

  if (!username || !password) {
    return { ...previous, username, error: "Enter your username and password." };
  }

  let result: LoginResponse;
  try {
    result = await apiFetch<LoginResponse>("/auth/login", {
      method: "POST",
      token: null,
      body: { username, password, totp: totp || null },
    });
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;

    // The API distinguishes "we need your one-time code" from "those details are
    // wrong", and the second message is deliberately the same whether it was the
    // username or the password that did not match.
    const needsTotp = error.code === "MFA_REQUIRED" || error.code === "TOTP_REQUIRED";
    return {
      username,
      needsTotp,
      mustChangePassword: false,
      error: error.message,
    };
  }

  await startSession(result.access_token);

  if (result.must_change_password) redirect("/settings/profile?change=1");
  redirect(next);
}

export async function logout(): Promise<void> {
  try {
    await apiFetch("/auth/logout", { method: "POST" });
  } catch {
    // Even if the API call fails, the local cookie must go: the user asked to leave.
  }
  await endSession();
  redirect("/login");
}
