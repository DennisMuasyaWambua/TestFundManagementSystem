/** The signed-in user, fetched once per request and shared by the whole render. */

import { cache } from "react";

import { apiFetch } from "@/lib/api/server";
import { ApiError } from "@/lib/api/errors";
import type { Me } from "@/lib/api/schema";
import { getToken } from "@/lib/auth/session";

/**
 * `cache` dedupes this across one render pass, so the layout, the sidebar and a
 * page component all see the same user without three round trips.
 */
export const currentUser = cache(async (): Promise<Me | null> => {
  if (!(await getToken())) return null;
  try {
    return await apiFetch<Me>("/me");
  } catch (error) {
    // An expired or revoked token is not an error here: the middleware and the
    // layout both treat "no user" as "sign in again".
    if (error instanceof ApiError && error.isUnauthenticated) return null;
    throw error;
  }
});

/** For pages that cannot render at all without a user. */
export async function requireUser(): Promise<Me> {
  const me = await currentUser();
  if (!me) throw new ApiError(401, "NOT_AUTHENTICATED", "your session has ended");
  return me;
}
