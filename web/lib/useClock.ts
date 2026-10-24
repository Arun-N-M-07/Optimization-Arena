"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/** Server-authoritative clock: remembers (server_now - local now) from the last API response. */
export function useServerClock() {
  const offset = useRef(0);
  const sync = useCallback((serverNow: string | null | undefined) => {
    if (serverNow) offset.current = new Date(serverNow).getTime() - Date.now();
  }, []);
  const now = useCallback(() => Date.now() + offset.current, []);
  return { sync, now };
}

export function formatRemaining(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return [h, m, sec].map((n) => String(n).padStart(2, "0")).join(":");
}

export function useTick(intervalMs = 1000) {
  const [, setT] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setT((t) => t + 1), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
}
