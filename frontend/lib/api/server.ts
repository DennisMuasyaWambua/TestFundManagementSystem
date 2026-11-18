/**
 * The server-side half of the backend-for-frontend.
 *
 * Only code that runs on the server imports this.  It is the one place that knows
 * the Python API's address and the user's token, so a Client Component can never
 * reach the API directly and the token can never reach the browser.
 */

import { ApiError } from "@/lib/api/errors";
import { getToken } from "@/lib/auth/session";

const API_BASE = process.env.FMS_API_URL ?? "http://localhost:8000/api/v1";

export type Query = Record<string, string | number | boolean | null | undefined>;

export function withQuery(path: string, query?: Query): string {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === null || value === undefined || value === "") continue;
    params.set(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

type RequestOptions = {
  method?: string;
  body?: unknown;
  /**
   * An already-serialised JSON body, forwarded byte for byte.
   *
   * The proxy uses this so a request never makes a parse/re-serialise round trip:
   * re-encoding could turn a JSON number like 1000000.00 into 1000000, and losing
   * those two zeros on the way to the ledger is exactly the class of bug the
   * string-money rule exists to prevent.
   */
  rawBody?: string;
  query?: Query;
  /** Pass a token explicitly during login, before the cookie exists. */
  token?: string | null;
  headers?: Record<string, string>;
  /** Reads are not cached by default: this is a ledger, staleness is a defect. */
  cache?: RequestCache;
  idempotencyKey?: string;
};

async function request(path: string, options: RequestOptions = {}): Promise<Response> {
  const token = options.token !== undefined ? options.token : await getToken();
  const headers: Record<string, string> = { accept: "application/json", ...options.headers };
  if (token) headers.authorization = `Bearer ${token}`;

  let body: BodyInit | undefined;
  if (options.body instanceof FormData) {
    body = options.body;
  } else if (options.rawBody !== undefined) {
    headers["content-type"] = "application/json";
    body = options.rawBody;
  } else if (options.body !== undefined) {
    headers["content-type"] = "application/json";
    body = JSON.stringify(options.body);
  }

  const method = options.method ?? "GET";
  if (method !== "GET" && options.idempotencyKey) {
    headers["idempotency-key"] = options.idempotencyKey;
  }

  return fetch(`${API_BASE}${withQuery(path, options.query)}`, {
    method,
    headers,
    body,
    cache: options.cache ?? "no-store",
  });
}

/** A JSON call that throws {@link ApiError} on any non-2xx reply. */
export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await request(path, options);
  if (!response.ok) throw await ApiError.fromResponse(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/**
 * A read that renders an empty state instead of an error page.
 *
 * Used for secondary panels on a dashboard: a 403 on one card must not blank the
 * whole screen for a role that simply cannot see that card.
 */
export async function apiFetchOrNull<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T | null> {
  try {
    return await apiFetch<T>(path, options);
  } catch (error) {
    if (error instanceof ApiError && (error.isForbidden || error.status === 404)) return null;
    throw error;
  }
}

/** A binary download (a PDF letter, a statement, an XLSX export). */
export async function apiFetchBlob(
  path: string,
  options: RequestOptions = {},
): Promise<{ body: ArrayBuffer; contentType: string; filename: string | null }> {
  const response = await request(path, { ...options, headers: { accept: "*/*" } });
  if (!response.ok) throw await ApiError.fromResponse(response);
  const disposition = response.headers.get("content-disposition") ?? "";
  const match = /filename="?([^";]+)"?/.exec(disposition);
  return {
    body: await response.arrayBuffer(),
    contentType: response.headers.get("content-type") ?? "application/octet-stream",
    filename: match?.[1] ?? null,
  };
}

/** The raw proxy path, used by the catch-all route handler. */
export function apiRequest(path: string, options: RequestOptions = {}): Promise<Response> {
  return request(path, options);
}
