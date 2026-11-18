"use client";

import { useEffect } from "react";

import { Button, ErrorBanner } from "@/components/ui/primitives";

/**
 * The error boundary for every signed-in screen.
 *
 * The message the API wrote is shown as it was written: these messages name the rule
 * that was broken -- insufficient cash, a locked period, a segregation breach -- and
 * that is exactly what the person reading needs. Replacing them with "something went
 * wrong" would hide the only useful part.
 */
export default function AppError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[fms]", error);
  }, [error]);

  const unauthenticated = /session|401|not authenticated/i.test(error.message);

  return (
    <div className="space-y-4">
      <ErrorBanner
        title={unauthenticated ? "Your session has ended" : "That did not work"}
        message={
          unauthenticated
            ? "Sign in again to carry on. Nothing you had not confirmed has been saved."
            : error.message
        }
        details={error.digest ? <span>Reference {error.digest}</span> : undefined}
      />

      <div className="flex gap-2">
        {unauthenticated ? (
          <Button type="button" onClick={() => window.location.assign("/login")}>
            Sign in again
          </Button>
        ) : (
          <>
            <Button type="button" onClick={reset}>
              Try again
            </Button>
            <Button
              variant="secondary"
              type="button"
              onClick={() => window.location.assign("/dashboard")}
            >
              Back to the dashboard
            </Button>
          </>
        )}
      </div>
    </div>
  );
}
