import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAutosave } from "./useAutosave";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());
const flushTimers = async (ms: number) => { await act(async () => { await vi.advanceTimersByTimeAsync(ms); }); };

describe("useAutosave", () => {
  it("debounces rapid edits into a single save of the latest value", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    const { result, rerender } = renderHook(({ v }) => useAutosave({ value: v, save, delay: 1000 }), { initialProps: { v: "a" } });
    rerender({ v: "ab" }); await flushTimers(400);
    rerender({ v: "abc" }); await flushTimers(400);
    expect(save).not.toHaveBeenCalled();
    expect(result.current.state).toBe("dirty");
    await flushTimers(1000);
    expect(save).toHaveBeenCalledTimes(1);
    expect(save).toHaveBeenCalledWith("abc");
    expect(result.current.state).toBe("saved");
  });

  it("does not save when nothing changed, and reset() re-baselines without saving", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    const { result, rerender } = renderHook(({ v }) => useAutosave({ value: v, save, delay: 500 }), { initialProps: { v: "x" } });
    await flushTimers(2000);
    expect(save).not.toHaveBeenCalled();
    act(() => result.current.reset("loaded draft"));
    rerender({ v: "loaded draft" });
    await flushTimers(2000);
    expect(save).not.toHaveBeenCalled();
  });

  it("flush() saves immediately", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    const { result, rerender } = renderHook(({ v }) => useAutosave({ value: v, save, delay: 60_000 }), { initialProps: { v: "a" } });
    rerender({ v: "b" });
    await act(async () => { await result.current.flush(); });
    expect(save).toHaveBeenCalledWith("b");
  });

  it("surfaces a failed save, then retries by itself with backoff and recovers", async () => {
    const save = vi.fn().mockRejectedValueOnce(new Error("network down")).mockResolvedValue(undefined);
    const { result, rerender } = renderHook(({ v }) => useAutosave({ value: v, save, delay: 100 }), { initialProps: { v: "a" } });
    rerender({ v: "b" }); await flushTimers(120);
    expect(result.current.state).toBe("error");
    expect(result.current.error).toBe("network down");
    await flushTimers(250);                                  // backoff: retry 200ms after the failed attempt
    expect(save).toHaveBeenCalledTimes(2);
    expect(result.current.state).toBe("saved");
    expect(result.current.error).toBeNull();
  });

  it("backs off while the error persists instead of retrying at a fixed rate", async () => {
    const save = vi.fn().mockRejectedValue(new Error("Round 1 is not open"));
    const { rerender } = renderHook(({ v }) => useAutosave({ value: v, save, delay: 100 }), { initialProps: { v: "a" } });
    rerender({ v: "b" });
    await flushTimers(120);   // attempt 1
    await flushTimers(210);   // attempt 2 (after 200ms)
    await flushTimers(410);   // attempt 3 (after 400ms)
    expect(save).toHaveBeenCalledTimes(3);
    await flushTimers(300);
    expect(save).toHaveBeenCalledTimes(3);                   // next one is 800ms away
  });

  it("never overlaps saves: an edit made while saving is saved afterwards", async () => {
    let release!: () => void;
    const save = vi.fn().mockImplementationOnce(() => new Promise<void>((r) => { release = r; })).mockResolvedValue(undefined);
    const { rerender } = renderHook(({ v }) => useAutosave({ value: v, save, delay: 100 }), { initialProps: { v: "a" } });
    rerender({ v: "b" }); await flushTimers(150);
    expect(save).toHaveBeenCalledTimes(1);
    rerender({ v: "c" }); await flushTimers(150);
    expect(save).toHaveBeenCalledTimes(1);          // still waiting for the first save
    await act(async () => { release(); await vi.advanceTimersByTimeAsync(300); });
    expect(save).toHaveBeenCalledTimes(2);
    expect(save).toHaveBeenLastCalledWith("c");
  });

  it("does nothing while disabled (e.g. the round is closed)", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    const { rerender } = renderHook(({ v }) => useAutosave({ value: v, save, delay: 100, enabled: false }), { initialProps: { v: "a" } });
    rerender({ v: "b" }); await flushTimers(1000);
    expect(save).not.toHaveBeenCalled();
  });

  it("warns before the page is left while edits are unsaved, and stops warning once saved", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    const { rerender } = renderHook(({ v }) => useAutosave({ value: v, save, delay: 100 }), { initialProps: { v: "a" } });
    const fire = () => { const e = new Event("beforeunload", { cancelable: true }); window.dispatchEvent(e); return e.defaultPrevented; };
    expect(fire()).toBe(false);                       // nothing to lose
    rerender({ v: "b" });
    expect(fire()).toBe(true);                        // unsaved edit: browser will ask before leaving
    await flushTimers(150);
    expect(fire()).toBe(false);                       // saved
  });
});
