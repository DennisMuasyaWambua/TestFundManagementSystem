/**
 * The session: a backend token the browser never sees.
 *
 * The token lives in an httpOnly, Secure, SameSite=Strict cookie, so script on the
 * page cannot read it and it is not sent on cross-site requests.  A separate,
 * readable CSRF cookie is paired with it: mutating requests must echo its value in a
 * header, which script from another origin cannot do.
 */

import { cookies } from "next/headers";

export const SESSION_COOKIE = "fms_session";
export const CSRF_COOKIE = "fms_csrf";
export const CSRF_HEADER = "x-fms-csrf";

/** Mirrors the backend's 30-minute access token. */
export const SESSION_MAX_AGE_SECONDS = 30 * 60;

export type SessionCookieOptions = {
  httpOnly: boolean;
  secure: boolean;
  sameSite: "strict";
  path: string;
  maxAge: number;
};

function cookieOptions(httpOnly: boolean): SessionCookieOptions {
  return {
    httpOnly,
    // Plain HTTP is only ever used for local development.
    secure: process.env.NODE_ENV === "production",
    sameSite: "strict",
    path: "/",
    maxAge: SESSION_MAX_AGE_SECONDS,
  };
}

export async function getToken(): Promise<string | null> {
  const store = await cookies();
  return store.get(SESSION_COOKIE)?.value ?? null;
}

export async function getCsrfToken(): Promise<string | null> {
  const store = await cookies();
  return store.get(CSRF_COOKIE)?.value ?? null;
}

export function newCsrfToken(): string {
  return crypto.randomUUID();
}

export async function startSession(token: string): Promise<void> {
  const store = await cookies();
  store.set(SESSION_COOKIE, token, cookieOptions(true));
  // Readable by script on purpose: the page has to be able to echo it back.
  store.set(CSRF_COOKIE, newCsrfToken(), cookieOptions(false));
}

export async function endSession(): Promise<void> {
  const store = await cookies();
  store.delete(SESSION_COOKIE);
  store.delete(CSRF_COOKIE);
}
