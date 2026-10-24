import { StatusBadge } from "./Badge";

export type RunResult = {
  outcome: string; passed_visible: number | null; total_visible: number | null; passed_hidden: number | null; total_hidden: number | null;
  runtime_ms: number | null; safe_message: string | null; provider: string | null; is_mock?: boolean;
};

/** Participant-facing verdict. Hidden tests appear only as pass counts; mock results are loudly labelled. */
export function ResultPanel({ result, kind }: { result: RunResult | null; kind?: string }) {
  if (!result) return <p className="text-sm text-muted">No results yet. Run your code to see the output here.</p>;
  const isMock = result.is_mock || result.provider === "mock";
  return (
    <div className="space-y-2 text-sm" data-testid="result-panel">
      {isMock && (
        <p role="note" className="rounded border border-amber-400/50 bg-amber-400/10 px-3 py-2 text-amber-200">
          MOCK RESULT — the judge is a test double. Your code was NOT executed and this says nothing about correctness.
        </p>
      )}
      <div className="flex flex-wrap items-center gap-3">
        {kind && <span className="text-xs text-muted uppercase">{kind === "FINAL" ? "Final submission" : "Run"}</span>}
        <StatusBadge status={isMock ? "MOCK" : result.outcome} />
        {!isMock && result.total_visible != null && result.outcome !== "SYSTEM_ERROR" && (
          <span className="text-muted">Visible tests {result.passed_visible ?? 0}/{result.total_visible}</span>
        )}
        {!isMock && result.total_hidden != null && result.outcome !== "SYSTEM_ERROR" && (
          <span className="text-muted">Hidden tests {result.passed_hidden ?? 0}/{result.total_hidden}</span>
        )}
        {result.runtime_ms != null && !isMock && <span className="text-muted">{result.runtime_ms} ms</span>}
      </div>
      {result.safe_message && !isMock && <p className="whitespace-pre-wrap text-muted">{result.safe_message}</p>}
    </div>
  );
}
