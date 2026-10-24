import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Monaco never loads in jsdom: model both a healthy editor and an editor that fails to load.
const mode = vi.hoisted(() => ({ loads: true }));
vi.mock("next/dynamic", async () => {
  const React = await import("react");
  return {
    default: () => function FakeMonaco(p: { defaultValue: string; onChange: (v: string) => void; onMount: () => void }) {
      React.useEffect(() => { if (mode.loads) p.onMount(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
      return mode.loads ? <textarea data-testid="fake-monaco" defaultValue={p.defaultValue} onChange={(e) => p.onChange(e.target.value)} /> : <div>Loading…</div>;
    },
  };
});
import { CodeEditor } from "./CodeEditor";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("CodeEditor", () => {
  it("uses Monaco when it loads and never shows the fallback", () => {
    mode.loads = true;
    render(<CodeEditor value="print(1)" onChange={() => {}} language="python" fallbackMs={1000} />);
    act(() => { vi.advanceTimersByTime(5000); });
    expect(screen.getByTestId("fake-monaco")).toHaveValue("print(1)");
    expect(screen.queryByLabelText("Code editor (plain)")).not.toBeInTheDocument();
  });

  it("falls back to a plain textarea if Monaco cannot load, so teams are never locked out", () => {
    mode.loads = false;
    const onChange = vi.fn();
    render(<CodeEditor value="int main(){}" onChange={onChange} language="cpp" fallbackMs={1000} />);
    expect(screen.queryByLabelText("Code editor (plain)")).not.toBeInTheDocument();
    act(() => { vi.advanceTimersByTime(1100); });
    const ta = screen.getByLabelText("Code editor (plain)");
    expect(ta).toHaveValue("int main(){}");
    expect(screen.getByText(/could not load/)).toBeInTheDocument();
  });
});
