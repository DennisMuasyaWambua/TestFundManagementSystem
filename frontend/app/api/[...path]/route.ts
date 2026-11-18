/**
 * The catch-all proxy: the only route the browser's own fetches ever reach.
 *
 * It attaches the backend token from the httpOnly cookie, so the token stays out of
 * the browser, and it requires a CSRF header on every mutating request, so a form on
 * another origin cannot drive this one.  Nothing here interprets the payload: the
 * Python API remains the only place business rules live.
 */

import { type NextRequest, NextResponse } from "next/server";

import { apiRequest } from "@/lib/api/server";
import { CSRF_HEADER, getCsrfToken } from "@/lib/auth/session";

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

async function proxy(request: NextRequest, path: string[]): Promise<NextResponse> {
  const method = request.method.toUpperCase();

  if (!SAFE_METHODS.has(method)) {
    const expected = await getCsrfToken();
    const presented = request.headers.get(CSRF_HEADER);
    if (!expected || presented !== expected) {
      return NextResponse.json(
        {
          error: {
            code: "CSRF_FAILED",
            message: "this request did not carry a valid CSRF token; reload the page",
          },
        },
        { status: 403 },
      );
    }
  }

  const target = `/${path.join("/")}${request.nextUrl.search}`;
  const contentType = request.headers.get("content-type") ?? "";

  const idempotencyKey = request.headers.get("idempotency-key");

  let form: FormData | undefined;
  let raw: string | undefined;
  if (!SAFE_METHODS.has(method)) {
    if (contentType.includes("multipart/form-data")) {
      form = await request.formData();
    } else {
      raw = (await request.text()) || undefined;
    }
  }

  const upstream = await apiRequest(target, {
    method,
    ...(form ? { body: form } : {}),
    ...(raw !== undefined ? { rawBody: raw } : {}),
    ...(idempotencyKey ? { idempotencyKey } : {}),
  });

  const upstreamType = upstream.headers.get("content-type") ?? "application/json";
  const headers = new Headers({ "content-type": upstreamType, "cache-control": "no-store" });
  const disposition = upstream.headers.get("content-disposition");
  if (disposition) headers.set("content-disposition", disposition);

  return new NextResponse(upstream.body, { status: upstream.status, headers });
}

type Context = { params: Promise<{ path: string[] }> };

export async function GET(request: NextRequest, context: Context): Promise<NextResponse> {
  return proxy(request, (await context.params).path);
}

export async function POST(request: NextRequest, context: Context): Promise<NextResponse> {
  return proxy(request, (await context.params).path);
}

export async function PATCH(request: NextRequest, context: Context): Promise<NextResponse> {
  return proxy(request, (await context.params).path);
}

export async function PUT(request: NextRequest, context: Context): Promise<NextResponse> {
  return proxy(request, (await context.params).path);
}

export async function DELETE(request: NextRequest, context: Context): Promise<NextResponse> {
  return proxy(request, (await context.params).path);
}
