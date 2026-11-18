"use client";

import { useTransition } from "react";

import { SessionTimeout } from "@/components/layout/SessionTimeout";
import { Button } from "@/components/ui/primitives";
import type { Me } from "@/lib/api/schema";
import { ROLE_LABEL } from "@/lib/auth/permissions";

export function TopBar({ me, signOut }: { me: Me; signOut: () => Promise<void> }) {
  const [pending, start] = useTransition();

  const end = () => start(() => void signOut());

  return (
    <>
      <div className="flex items-center justify-between gap-4 border-b border-border bg-surface px-5 py-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-ink">{me.name}</p>
          <p className="truncate text-xs text-muted">
            {me.title} · {ROLE_LABEL[me.role]}
          </p>
        </div>
        <Button
          variant="secondary"
          type="button"
          onClick={end}
          disabled={pending}
          className="px-3 py-1.5"
        >
          {pending ? "Signing out…" : "Sign out"}
        </Button>
      </div>
      <SessionTimeout onSignOut={end} />
    </>
  );
}
