import type { Metadata } from "next";

import { LoginForm } from "@/app/(auth)/login/LoginForm";

export const metadata: Metadata = { title: "Sign in" };

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string }>;
}) {
  const { next } = await searchParams;
  const target = next && next.startsWith("/") && !next.startsWith("//") ? next : "/dashboard";

  return (
    <main id="content" className="flex min-h-screen items-center justify-center px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-6 text-center">
          <h1 className="text-lg font-semibold text-ink">Fund Management</h1>
          <p className="mt-1 text-sm text-muted">Segregated client mandates</p>
        </div>

        <div className="rounded-card border border-border bg-surface px-6 py-6 shadow-xs">
          <LoginForm next={target} />
        </div>

        <p className="mt-6 text-center text-xs text-muted">
          Client money is held in trust by appointed custodian banks and is never
          commingled with the firm&rsquo;s own assets.
        </p>
      </div>
    </main>
  );
}
