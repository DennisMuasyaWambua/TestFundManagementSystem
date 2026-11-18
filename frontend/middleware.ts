/**
 * Unauthenticated users go to /login, keeping where they were headed.
 *
 * This is a redirect, not a security control: every protected page also fetches the
 * user, and the API rejects any request without a valid token.  The middleware only
 * saves a signed-out user from watching a page render and then blank.
 */

import { type NextRequest, NextResponse } from "next/server";

import { SESSION_COOKIE } from "@/lib/auth/session";

const PUBLIC_PATHS = ["/login", "/api/auth"];

export function middleware(request: NextRequest): NextResponse {
  const { pathname, search } = request.nextUrl;

  if (PUBLIC_PATHS.some((prefix) => pathname.startsWith(prefix))) {
    return NextResponse.next();
  }

  if (request.cookies.has(SESSION_COOKIE)) {
    return NextResponse.next();
  }

  const login = request.nextUrl.clone();
  login.pathname = "/login";
  login.search = "";
  if (pathname !== "/") login.searchParams.set("next", `${pathname}${search}`);
  return NextResponse.redirect(login);
}

export const config = {
  // Everything except Next's own assets and the proxy (which returns 401 as JSON,
  // which the client fetch wrapper turns into a redirect).
  matcher: ["/((?!_next/static|_next/image|favicon.ico|api/).*)"],
};
