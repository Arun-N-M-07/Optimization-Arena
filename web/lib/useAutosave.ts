"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export type SaveState = "idle" | "dirty" | "saving" | "saved" | "error";

/**
 * Debounced autosave. A change to `value` marks the state dirty; one save fires `delay` ms after the last
 * change. `flush()` saves immediately (before run/submit/language switch). Saves never overlap: a change
 * made during a save is saved afterwards. `reset(value)` re-baselines without saving (after loading a draft).
 */
export function useAutosave<T>({ value, save, delay = 1500, enabled = true }:
  { value: T; save: (v: T) => Promise<void>; delay?: number; enabled?: boolean }) {
  const [state, setState] = useState<SaveState>("idle");
  const [error, setError] = useState<string | null>(null);
  const baseline = useRef<T>(value);
  const latest = useRef<T>(value);
  const inFlight = useRef<Promise<void> | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const failures = useRef(0);
  const cfg = useRef({ save, enabled, delay });
  const run = useRef<() => Promise<void>>(async () => {});
  const schedule = useRef<() => void>(() => {});

  useEffect(() => { cfg.current = { save, enabled, delay }; });

  useEffect(() => {
    schedule.current = () => {
      if (timer.current) clearTimeout(timer.current);
      // capped exponential backoff after failures, so a persistent error (e.g. a closed round) does not hammer the API
      timer.current = setTimeout(() => void run.current(), Math.min(cfg.current.delay * 2 ** failures.current, 30_000));
    };
    run.current = async () => {
      if (timer.current) clearTimeout(timer.current);
      timer.current = null;
      if (inFlight.current) await inFlight.current;
      if (Object.is(latest.current, baseline.current)) return;
      const sending = latest.current;
      setState("saving");
      const p = (async () => {
        try {
          await cfg.current.save(sending);
          baseline.current = sending;
          failures.current = 0;
          setError(null);
          setState(Object.is(latest.current, sending) ? "saved" : "dirty");
        } catch (e) {
          failures.current += 1;
          setError(e instanceof Error ? e.message : "Save failed");
          setState("error");
        }
      })();
      inFlight.current = p;
      await p;
      inFlight.current = null;
      if (!Object.is(latest.current, baseline.current) && cfg.current.enabled) schedule.current();
    };
    return () => { if (timer.current) clearTimeout(timer.current); };
  }, []);

  useEffect(() => {
    latest.current = value;
    if (!enabled || Object.is(value, baseline.current)) return;
    setState("dirty");
    schedule.current();
  }, [value, enabled]);

  // Warn before leaving while edits are unsaved, saving, or failed to save (prevents silent loss of work).
  useEffect(() => {
    if (state !== "dirty" && state !== "saving" && state !== "error") return;
    const guard = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [state]);

  const flush = useCallback(() => run.current(), []);
  const reset = useCallback((v: T) => {
    if (timer.current) clearTimeout(timer.current);
    baseline.current = v;
    latest.current = v;
    failures.current = 0;
    setState("idle");
    setError(null);
  }, []);

  return { state, error, flush, reset };
}
