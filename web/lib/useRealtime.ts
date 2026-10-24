"use client";

import { useEffect, useRef, useState } from "react";
import { createClient } from "@/lib/supabase/client";

export type LiveState = "connecting" | "live" | "reconnecting";

/**
 * Realtime is only a hint. Any change event, reconnect, tab refocus, `online` event or the polling
 * timer calls `refetch`, which reads the authoritative state from the backend. If Realtime is down the
 * page keeps working via polling.
 */
export function useRealtimeRefetch(refetch: () => void, tables: string[] = ["contest_sessions", "contest_announcements"], pollMs = 15000) {
  const [live, setLive] = useState<LiveState>("connecting");
  const cb = useRef(refetch);
  useEffect(() => { cb.current = refetch; });
  const key = tables.join(",");

  useEffect(() => {
    const supabase = createClient();
    let ch = supabase.channel(`arena-${key}-${Math.random().toString(36).slice(2)}`);
    for (const table of key.split(",")) ch = ch.on("postgres_changes", { event: "*", schema: "public", table }, () => cb.current());
    let wasLive = false;
    ch.subscribe((status) => {
      if (status === "SUBSCRIBED") {
        setLive("live");
        if (wasLive) cb.current();      // recovered after a drop: pull authoritative state
        wasLive = true;
      } else if (status === "CHANNEL_ERROR" || status === "TIMED_OUT" || status === "CLOSED") {
        setLive("reconnecting");
      }
    });
    const poll = setInterval(() => cb.current(), pollMs);
    const wake = () => { if (document.visibilityState === "visible") cb.current(); };
    document.addEventListener("visibilitychange", wake);
    window.addEventListener("online", wake);
    return () => {
      clearInterval(poll);
      document.removeEventListener("visibilitychange", wake);
      window.removeEventListener("online", wake);
      void supabase.removeChannel(ch);
    };
  }, [key, pollMs]);

  return live;
}
