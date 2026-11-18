"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/primitives";

const WARN_AFTER_MS = 25 * 60 * 1000;
const SIGN_OUT_AFTER_MS = 30 * 60 * 1000;

/**
 * Idle sign-out, warning five minutes before.
 *
 * The backend token expires after thirty minutes regardless; this makes the end of
 * the session visible instead of letting a signatory discover it halfway through
 * approving a payment. Any real interaction resets the clock.
 */
export function SessionTimeout({ onSignOut }: { onSignOut: () => void }) {
  const [warning, setWarning] = useState(false);
  const [secondsLeft, setSecondsLeft] = useState(0);
  const lastActivity = useRef(Date.now());

  const reset = useCallback(() => {
    lastActivity.current = Date.now();
    setWarning(false);
  }, []);

  useEffect(() => {
    const events: (keyof DocumentEventMap)[] = [
      "pointerdown",
      "keydown",
      "visibilitychange",
    ];
    for (const event of events) document.addEventListener(event, reset);

    const tick = window.setInterval(() => {
      const idle = Date.now() - lastActivity.current;
      if (idle >= SIGN_OUT_AFTER_MS) {
        onSignOut();
        return;
      }
      if (idle >= WARN_AFTER_MS) {
        setWarning(true);
        setSecondsLeft(Math.ceil((SIGN_OUT_AFTER_MS - idle) / 1000));
      }
    }, 1000);

    return () => {
      for (const event of events) document.removeEventListener(event, reset);
      window.clearInterval(tick);
    };
  }, [reset, onSignOut]);

  if (!warning) return null;

  const minutes = Math.floor(secondsLeft / 60);
  const seconds = `${secondsLeft % 60}`.padStart(2, "0");

  return (
    <div
      role="alertdialog"
      aria-live="assertive"
      className="fixed inset-x-4 bottom-4 z-50 mx-auto max-w-md rounded-card border border-warning-ink/20 bg-warning-tint px-4 py-3 shadow-lg sm:inset-x-auto sm:right-4"
    >
      <p className="text-sm font-semibold text-warning-ink">Your session is about to end</p>
      <p className="mt-0.5 text-sm text-warning-ink">
        You will be signed out in{" "}
        <span className="tnum font-medium">
          {minutes}:{seconds}
        </span>{" "}
        unless you carry on working.
      </p>
      <div className="mt-3 flex gap-2">
        <Button type="button" onClick={reset} className="px-3 py-1.5">
          Stay signed in
        </Button>
        <Button variant="secondary" type="button" onClick={onSignOut} className="px-3 py-1.5">
          Sign out now
        </Button>
      </div>
    </div>
  );
}
