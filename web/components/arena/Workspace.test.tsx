import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ api }));
vi.mock("./CodeEditor", () => ({
  CodeEditor: (p: { value: string; onChange: (v: string) => void; readOnly?: boolean }) =>
    <textarea aria-label="code" value={p.value} readOnly={p.readOnly} onChange={(e) => p.onChange(e.target.value)} />,
}));
import { Workspace, type Question } from "./Workspace";

const Q: Question = { round: 1, category: "DSA", question_id: "q1", title: "Dedupe", difficulty: "EASY", variant_id: "v1", label: "A",
  description: "Remove duplicates from a list.", expected_behavior: "Same output.", constraints: "n <= 1e5", languages: ["python", "cpp"],
  original_code: { python: "# slow python", cpp: "// slow cpp" }, visible_tests: [{ input: "1 1", expected_output: "1" }] };

type Call = [string, RequestInit | undefined];
function setup(overrides: Record<string, (init?: RequestInit) => unknown> = {}) {
  api.mockImplementation(async (path: string, init?: RequestInit) => {
    for (const [k, fn] of Object.entries(overrides)) if (path.endsWith(k)) return fn(init);
    if (path.endsWith("/drafts")) return { drafts: {} };
    if (path.endsWith("/submissions")) return { submissions: [] };
    if (path.endsWith("/draft")) return { saved: true };
    return {};
  });
}
const calls = (suffix: string) => (api.mock.calls as Call[]).filter(([p]) => p.endsWith(suffix));

beforeEach(() => { api.mockReset(); vi.spyOn(window, "confirm").mockReturnValue(true); });

describe("Workspace", () => {
  it("starts from the original code when there is no draft", async () => {
    setup();
    render(<Workspace q={Q} open showReport />);
    expect(await screen.findByLabelText("code")).toHaveValue("# slow python");
  });

  it("restores a saved draft after a refresh instead of the starter code", async () => {
    setup({ "/drafts": () => ({ drafts: { python: { code: "print('my draft')" } } }) });
    render(<Workspace q={Q} open showReport />);
    await waitFor(() => expect(screen.getByLabelText("code")).toHaveValue("print('my draft')"));
  });

  it("autosaves edits to the correct question and language", async () => {
    setup();
    render(<Workspace q={Q} open showReport />);
    const ed = await screen.findByLabelText("code");
    vi.useFakeTimers({ shouldAdvanceTime: true });
    await userEvent.type(ed, "!", { advanceTimers: vi.advanceTimersByTime });
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    vi.useRealTimers();
    const put = calls("/draft").at(-1)!;
    expect(put[0]).toBe("/participant/variants/v1/draft");
    expect(JSON.parse(put[1]!.body as string)).toEqual({ language: "python", code: "# slow python!" });
    expect(screen.getByTestId("save-status")).toHaveTextContent("Draft saved");
  });

  it("keeps separate drafts per language and flushes before switching", async () => {
    setup({ "/drafts": () => ({ drafts: { cpp: { code: "// cpp draft" } } }) });
    render(<Workspace q={Q} open showReport />);
    const ed = await screen.findByLabelText("code");
    await userEvent.type(ed, "X");
    await userEvent.selectOptions(screen.getByLabelText("Language"), "cpp");
    expect(screen.getByLabelText("code")).toHaveValue("// cpp draft");
    const saved = calls("/draft").map(([, i]) => JSON.parse(i!.body as string));
    expect(saved.some((b) => b.language === "python" && b.code === "# slow pythonX")).toBe(true);   // python work was flushed first
  });

  it("submits with an idempotency key, shows the labelled mock result, and refreshes history", async () => {
    const result = { outcome: "ACCEPTED", passed_visible: 1, total_visible: 1, passed_hidden: 1, total_hidden: 1, runtime_ms: 1, safe_message: "MOCK RESULT — your code was NOT executed.", provider: "mock", is_mock: true };
    setup({ "/submit": () => ({ result, duplicate: false }) });
    render(<Workspace q={Q} open showReport />);
    await screen.findByLabelText("code");
    await userEvent.click(screen.getByRole("button", { name: "Submit final solution" }));
    await waitFor(() => expect(screen.getByRole("note")).toHaveTextContent(/NOT executed/));
    const [, init] = calls("/submit")[0];
    expect((init!.headers as Record<string, string>)["Idempotency-Key"]).toMatch(/^[0-9a-f-]{36}$/);
    expect(calls("/submissions").length).toBeGreaterThanOrEqual(2);       // loaded on mount and after submit
  });

  it("does nothing if the participant cancels the submit confirmation", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    setup();
    render(<Workspace q={Q} open showReport />);
    await screen.findByLabelText("code");
    await userEvent.click(screen.getByRole("button", { name: "Submit final solution" }));
    expect(calls("/submit")).toHaveLength(0);
  });

  it("shows server errors such as a closed round", async () => {
    setup({ "/run": () => { throw new Error("Round 1 is not open for submissions (state: ENDED)"); } });
    render(<Workspace q={Q} open showReport />);
    await screen.findByLabelText("code");
    await userEvent.click(screen.getByRole("button", { name: "Run" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/not open/);
  });

  it("is read-only and cannot run or submit when the round is closed", async () => {
    setup();
    render(<Workspace q={Q} open={false} showReport />);
    const ed = await screen.findByLabelText("code");
    expect(ed).toHaveAttribute("readonly");
    expect(screen.getByRole("button", { name: "Run" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Submit final solution" })).toBeDisabled();
    expect(screen.getByText(/not accepting changes/)).toBeInTheDocument();
  });

  it("restores starter code only after confirmation", async () => {
    setup({ "/drafts": () => ({ drafts: { python: { code: "mine" } } }) });
    render(<Workspace q={Q} open showReport />);
    await waitFor(() => expect(screen.getByLabelText("code")).toHaveValue("mine"));
    vi.spyOn(window, "confirm").mockReturnValueOnce(false);
    await userEvent.click(screen.getByRole("button", { name: "Restore starter code" }));
    expect(screen.getByLabelText("code")).toHaveValue("mine");
    await userEvent.click(screen.getByRole("button", { name: "Restore starter code" }));
    expect(screen.getByLabelText("code")).toHaveValue("# slow python");
  });

  it("hides the report tab in Round 2", async () => {
    setup();
    render(<Workspace q={{ ...Q, round: 2, category: "DUEL" }} open showReport={false} />);
    await screen.findByLabelText("code");
    expect(screen.queryByRole("tab", { name: "Autopsy Report" })).not.toBeInTheDocument();
  });

  it("REGRESSION: a late, stale report response never wipes text the participant has typed (and is never autosaved as empty)", async () => {
    // StrictMode double-invokes the load effect: the first request is stale. It resolves AFTER the user typed.
    const resolvers: ((v: unknown) => void)[] = [];
    const empty = { report: null, limits: { max: 4000, min_to_submit: 30 } };
    api.mockImplementation((path: string, init?: RequestInit) => {
      if (path.endsWith("/report") && !init) return new Promise((r) => resolvers.push(r));
      if (path.endsWith("/drafts")) return Promise.resolve({ drafts: {} });
      if (path.endsWith("/submissions")) return Promise.resolve({ submissions: [] });
      return Promise.resolve({ saved: true });
    });
    render(<StrictMode><Workspace q={Q} open showReport /></StrictMode>);
    await userEvent.click(await screen.findByRole("tab", { name: "Autopsy Report" }));
    await waitFor(() => expect(resolvers.length).toBeGreaterThanOrEqual(2));
    await act(async () => { resolvers.at(-1)!(empty); });                          // the current request answers: form appears
    const box = await screen.findByLabelText(/Inefficiency identification/);
    await userEvent.type(box, "my careful analysis");
    await act(async () => { resolvers[0](empty); });                                 // the STALE request answers late
    expect(screen.getByLabelText(/Inefficiency identification/)).toHaveValue("my careful analysis");
    await act(async () => { await new Promise((r) => setTimeout(r, 2000)); });      // let autosave run
    const puts = (api.mock.calls as Call[]).filter(([p, i]) => p.endsWith("/report") && i?.method === "PUT").map(([, i]) => JSON.parse(i!.body as string));
    expect(puts.length).toBeGreaterThan(0);
    expect(puts.every((b) => b.inefficiency === "my careful analysis")).toBe(true);  // never an empty overwrite
  }, 15000);
});
