"use client";

import { formatRemaining, useTick } from "@/lib/useClock";

/** Counts down to a server timestamp using the server-synced `now`. The browser clock never decides anything. */
export function Countdown({ endsAt, now, state }: { endsAt: string | null; now: () => number; state: string }) {
  useTick();
  if (state === "ENDED" || state === "RESULTS_PUBLISHED") return <span className="font-mono text-muted" data-testid="countdown">Ended</span>;
  if (!endsAt) return <span className="font-mono text-muted" data-testid="countdown">—</span>;
  const left = new Date(endsAt).getTime() - now();
  if (left <= 0) return <span className="font-mono text-danger" data-testid="countdown">Time is up</span>;
  return <span className={`font-mono ${left < 5 * 60_000 ? "text-danger" : ""}`} data-testid="countdown" aria-label="Time remaining">{formatRemaining(left)}</span>;
}
