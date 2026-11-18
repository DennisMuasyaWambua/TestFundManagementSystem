"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";

import { ApiError } from "@/lib/api/errors";

/**
 * TanStack Query, configured for a ledger rather than a feed.
 *
 * Balances and instruction states are never served stale on purpose, and a failed
 * permission or business-rule check is not retried: repeating a 403 or a 422 cannot
 * change the answer and only delays the error the user needs to read.
 */
export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 0,
            refetchOnWindowFocus: true,
            retry: (attempt, error) => {
              if (error instanceof ApiError && error.status < 500) return false;
              return attempt < 2;
            },
          },
          mutations: { retry: false },
        },
      }),
  );

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
