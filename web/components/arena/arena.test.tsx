import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { StatusBadge } from "./Badge";
import { Countdown } from "./Countdown";
import { ReportForm, type ReportValue } from "./ReportForm";
import { ResultPanel } from "./ResultPanel";
import { formatRemaining } from "@/lib/useClock";

const FULL: ReportValue = { inefficiency: "x".repeat(40), approach: "y".repeat(40), complexity: "z".repeat(40), tradeoffs: "w".repeat(40) };
const props = { max: 4000, min: 30, saveState: "idle" as const, onSubmit: vi.fn(), onAmend: vi.fn(), busy: false, error: null, canEdit: true };

describe("ReportForm", () => {
  it("shows four independently labelled sections with live counters", () => {
    render(<ReportForm {...props} value={{ ...FULL, approach: "short" }} onChange={() => {}} status="DRAFT" />);
    for (const t of [/Inefficiency identification/, /Optimization approach/, /Complexity analysis/, /Trade-offs and reasoning/]) expect(screen.getByLabelText(t)).toBeInTheDocument();
    expect(screen.getByText(/5\/4000 — at least 30 characters/)).toBeInTheDocument();
  });

  it("blocks submission until every section meets the minimum, then allows it", async () => {
    const onSubmit = vi.fn();
    const { rerender } = render(<ReportForm {...props} onSubmit={onSubmit} value={{ ...FULL, tradeoffs: "tiny" }} onChange={() => {}} status="DRAFT" />);
    expect(screen.getByRole("button", { name: "Submit report" })).toBeDisabled();
    rerender(<ReportForm {...props} onSubmit={onSubmit} value={FULL} onChange={() => {}} status="DRAFT" />);
    await userEvent.click(screen.getByRole("button", { name: "Submit report" }));
    expect(onSubmit).toHaveBeenCalledOnce();
  });

  it("propagates edits per section", async () => {
    const onChange = vi.fn();
    render(<ReportForm {...props} value={{ inefficiency: "", approach: "", complexity: "", tradeoffs: "" }} onChange={onChange} status="DRAFT" />);
    await userEvent.type(screen.getByLabelText(/Complexity analysis/), "O");
    expect(onChange).toHaveBeenCalledWith({ inefficiency: "", approach: "", complexity: "O", tradeoffs: "" });
  });

  it("is read-only once submitted and offers an amendment instead", async () => {
    const onAmend = vi.fn();
    render(<ReportForm {...props} onAmend={onAmend} value={FULL} onChange={() => {}} status="EVALUATION_PENDING" />);
    expect(screen.getByLabelText(/Optimization approach/)).toHaveAttribute("readonly");
    expect(screen.queryByRole("button", { name: "Submit report" })).not.toBeInTheDocument();
    expect(screen.getByText(/can no longer be edited/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /amendment/ }));
    expect(onAmend).toHaveBeenCalledOnce();
  });

  it.each([
    ["PENDING", /queued or running/, "Evaluating"],
    ["DELAYED", /did not finish.*retry.*do not need to resubmit/, "Evaluation delayed"],
    ["COMPLETE", /has been evaluated/, "Evaluating"],
  ] as const)("tells a submitted participant the real evaluation state: %s", (state, text, badge) => {
    render(<ReportForm {...props} value={FULL} onChange={() => {}} status={state === "COMPLETE" ? "EVALUATED" : "EVALUATION_PENDING"} evaluation={state} />);
    expect(screen.getByTestId("evaluation-status")).toHaveTextContent(text);
    expect(screen.getByTestId("evaluation-status")).toHaveAttribute("data-state", state);
    if (state !== "COMPLETE") expect(screen.getByText(badge)).toBeInTheDocument();
  });

  it("never claims the evaluation succeeded after a failure, and says nothing for drafts", () => {
    const { rerender } = render(<ReportForm {...props} value={FULL} onChange={() => {}} status="EVALUATION_PENDING" evaluation="DELAYED" />);
    expect(screen.getByTestId("evaluation-status")).not.toHaveTextContent(/has been evaluated/);
    expect(screen.queryByText("Evaluating")).not.toBeInTheDocument();
    rerender(<ReportForm {...props} value={FULL} onChange={() => {}} status="DRAFT" evaluation={null} />);
    expect(screen.queryByTestId("evaluation-status")).not.toBeInTheDocument();
  });

  it("shows save errors and server errors", () => {
    render(<ReportForm {...props} value={FULL} onChange={() => {}} status="DRAFT" saveState="error" saveError="offline" error="Round 1 is not open" />);
    expect(screen.getByText(/Could not save: offline/)).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Round 1 is not open");
  });
});

describe("ResultPanel", () => {
  const base = { outcome: "ACCEPTED", passed_visible: 2, total_visible: 2, passed_hidden: 1, total_hidden: 1, runtime_ms: 12, safe_message: "ok", provider: "real" };
  it("renders an empty state", () => { render(<ResultPanel result={null} />); expect(screen.getByText(/No results yet/)).toBeInTheDocument(); });
  it("labels mock results loudly and never presents them as a correctness verdict", () => {
    render(<ResultPanel kind="FINAL" result={{ ...base, provider: "mock", is_mock: true, safe_message: "MOCK RESULT — your code was NOT executed. This is not a correctness verdict." }} />);
    expect(screen.getByRole("note")).toHaveTextContent(/NOT executed/);
    expect(screen.queryByText(/Visible tests/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Hidden tests/)).not.toBeInTheDocument();
    expect(screen.queryByText("Accepted")).not.toBeInTheDocument();             // a fake verdict is never shown as if it were real
    expect(screen.getByText("Mock — not executed")).toBeInTheDocument();
  });
  it("shows hidden tests only as counts for real results", () => {
    render(<ResultPanel result={base} />);
    expect(screen.getByText("Visible tests 2/2")).toBeInTheDocument();
    expect(screen.getByText("Hidden tests 1/1")).toBeInTheDocument();
  });
  it("does not report counts for a system error", () => {
    render(<ResultPanel result={{ ...base, outcome: "SYSTEM_ERROR", passed_visible: null, passed_hidden: null, provider: "disabled", safe_message: "Code execution is not enabled" }} />);
    expect(screen.getByText("System error")).toBeInTheDocument();
    expect(screen.queryByText(/Visible tests/)).not.toBeInTheDocument();
  });
});

describe("StatusBadge", () => {
  it("humanises statuses and ignores empty ones", () => {
    const { container, rerender } = render(<StatusBadge status="EVALUATION_PENDING" />);
    expect(screen.getByText("Evaluating")).toBeInTheDocument();
    rerender(<StatusBadge status="WRONG_ANSWER" />);
    expect(screen.getByText("Wrong answer")).toBeInTheDocument();
    rerender(<StatusBadge status={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("Countdown", () => {
  it("counts down from the server-synced clock, not the browser clock", () => {
    vi.useFakeTimers();
    const serverNow = new Date("2026-10-24T10:00:00Z").getTime();
    const now = () => serverNow;                       // server says it is 10:00:00 regardless of Date.now()
    render(<Countdown endsAt="2026-10-24T10:30:00Z" now={now} state="RUNNING" />);
    expect(screen.getByTestId("countdown")).toHaveTextContent("00:30:00");
    vi.useRealTimers();
  });
  it("shows the end states", () => {
    const { rerender } = render(<Countdown endsAt="2026-10-24T10:00:00Z" now={() => new Date("2026-10-24T10:00:01Z").getTime()} state="RUNNING" />);
    expect(screen.getByTestId("countdown")).toHaveTextContent("Time is up");
    rerender(<Countdown endsAt={null} now={() => 0} state="ENDED" />);
    expect(screen.getByTestId("countdown")).toHaveTextContent("Ended");
  });
  it("formats durations", () => { expect(formatRemaining(3_661_000)).toBe("01:01:01"); expect(formatRemaining(-5)).toBe("00:00:00"); });
});
