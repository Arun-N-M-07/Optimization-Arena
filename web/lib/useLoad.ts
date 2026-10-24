"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

/** Loads JSON from the backend and exposes reload + error. */
export function useLoad<T>(path: string) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reload = useCallback(async () => {
    try {
      setData(await api<T>(path));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    }
  }, [path]);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void reload();
  }, [reload]);
  return { data, error, reload };
}

export function errText(e: unknown): string {
  if (e instanceof Error) {
    try {
      const j = JSON.parse(e.message);
      if (j?.message) return [j.message, ...(j.problems ?? [])].join(" — ");
    } catch {}
    return e.message;
  }
  return "Something went wrong";
}
