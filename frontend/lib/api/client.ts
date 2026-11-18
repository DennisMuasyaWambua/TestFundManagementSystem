"use client";

/**
 * The browser-side fetch wrapper.
 *
 * Everything goes to this app's own `/api/...` proxy, never to the Python API, so
 * the backend token stays in an httpOnly cookie.  Mutating calls carry the CSRF
 * token the proxy expects, and a 401 sends the user to /login with a return URL
 * rather than leaving a half-rendered screen behind.
 */

import { ApiError } from "@/lib/api/errors";

const CSRF_HEADER = "x-fms-csrf";
const CSRF_COOKIE = "fms_csrf";

function csrfToken(): string {
  const match = document.cookie.match(new RegExp(`(?:^|; )${CSRF_COOKIE}=([^;]*)`));
  return match?.[1] ? decodeURIComponent(match[1]) : "";
}

export function redirectToLogin(): void {
  const here = `${window.location.pathname}${window.location.search}`;
  const next = here === "/" ? "" : `?next=${encodeURIComponent(here)}`;
  window.location.assign(`/login${next}`);
}

type Options = {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
  /** Set on a retryable money-moving call so a repeat cannot post twice. */
  idempotencyKey?: string;
};

async function call(path: string, options: Options = {}): Promise<Response> {
  const method = options.method ?? "GET";
  const headers: Record<string, string> = { accept: "application/json" };

  let body: BodyInit | undefined;
  if (options.body instanceof FormData) {
    body = options.body;
  } else if (options.body !== undefined) {
    headers["content-type"] = "application/json";
    body = JSON.stringify(options.body);
  }

  if (method !== "GET") {
    headers[CSRF_HEADER] = csrfToken();
    if (options.idempotencyKey) headers["idempotency-key"] = options.idempotencyKey;
  }

  const response = await fetch(`/api/v1${path}`, {
    method,
    headers,
    body,
    signal: options.signal,
    credentials: "same-origin",
  });

  if (response.status === 401) {
    redirectToLogin();
    throw new ApiError(401, "NOT_AUTHENTICATED", "your session has ended; signing in again");
  }
  return response;
}

export async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await call(path, signal ? { signal } : {});
  if (!response.ok) throw await ApiError.fromResponse(response);
  return (await response.json()) as T;
}

export async function apiSend<T>(
  path: string,
  options: Omit<Options, "signal"> & { method: "POST" | "PATCH" | "PUT" | "DELETE" },
): Promise<T> {
  const response = await call(path, options);
  if (!response.ok) throw await ApiError.fromResponse(response);
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

/** A fresh key per attempt of a money-moving action. */
export function newIdempotencyKey(): string {
  return crypto.randomUUID();
}
