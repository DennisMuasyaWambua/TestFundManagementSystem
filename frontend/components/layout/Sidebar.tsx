"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { NAV } from "@/components/layout/nav";
import type { Me } from "@/lib/api/schema";
import { ROLE_LABEL, canAny } from "@/lib/auth/permissions";
import { cn } from "@/lib/cn";

/**
 * The fixed left sidebar, which stacks above the content below 768px.
 *
 * Entries the user's role cannot act on are hidden -- but only as a courtesy: the
 * API enforces every one of these permissions, and a user who navigates straight to
 * a hidden URL gets the API's 403, rendered as a page they can read.
 */
export function Sidebar({ me }: { me: Me }) {
  const pathname = usePathname();

  const groups = NAV.map((group) => ({
    ...group,
    items: group.items.filter(
      (item) => !item.permissions || canAny(me, ...item.permissions),
    ),
  })).filter((group) => group.items.length > 0);

  return (
    <nav
      aria-label="Main"
      className="bg-sidebar text-sidebar-ink md:fixed md:inset-y-0 md:left-0 md:w-64 md:overflow-y-auto"
    >
      <div className="px-5 py-5">
        <Link href="/dashboard" className="block">
          <p className="text-sm font-semibold tracking-tight">Fund Management</p>
          <p className="mt-0.5 text-xs text-sidebar-muted">Segregated client mandates</p>
        </Link>
      </div>

      <div className="px-3 pb-6">
        {groups.map((group) => (
          <div key={group.heading} className="mb-5">
            <p className="px-2 pb-1.5 text-[0.68rem] font-semibold tracking-widest text-sidebar-muted uppercase">
              {group.heading}
            </p>
            <ul className="space-y-0.5">
              {group.items.map((item) => {
                const active =
                  pathname === item.href || pathname.startsWith(`${item.href}/`);
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "flex min-h-11 items-center rounded-lg px-2 text-sm transition-colors",
                        active
                          ? "bg-white/10 font-medium text-white"
                          : "text-sidebar-ink hover:bg-white/5",
                      )}
                    >
                      {item.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>

      <div className="border-t border-white/10 px-5 py-4 md:absolute md:inset-x-0 md:bottom-0 md:bg-sidebar">
        <p className="truncate text-sm font-medium">{me.name}</p>
        <p className="truncate text-xs text-sidebar-muted">{ROLE_LABEL[me.role]}</p>
      </div>
    </nav>
  );
}
