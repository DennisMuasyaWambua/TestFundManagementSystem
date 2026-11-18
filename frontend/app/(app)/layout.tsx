import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { logout } from "@/app/(auth)/login/actions";
import { Sidebar } from "@/components/layout/Sidebar";
import { TopBar } from "@/components/layout/TopBar";
import { currentUser } from "@/lib/auth/me";

/**
 * The shell every signed-in screen renders inside.
 *
 * The user is fetched once here and reused by the whole render pass, so a page and
 * its sidebar can never disagree about who is signed in or what they may do.
 */
export default async function AppLayout({ children }: { children: ReactNode }) {
  const me = await currentUser();
  if (!me) redirect("/login");

  return (
    <div className="md:pl-64">
      <Sidebar me={me} />
      <div className="flex min-h-screen flex-col">
        <TopBar me={me} signOut={logout} />
        <main id="content" className="mx-auto w-full max-w-[1240px] flex-1 px-4 py-6 sm:px-6">
          {children}
        </main>
        <footer className="mx-auto w-full max-w-[1240px] px-4 pb-8 sm:px-6">
          <p className="border-t border-border pt-4 text-xs text-muted">
            Client funds are held in trust by appointed custodian banks, segregated by
            mandate, and are not assets of the firm. All records are retained for seven
            years.
          </p>
        </footer>
      </div>
    </div>
  );
}
