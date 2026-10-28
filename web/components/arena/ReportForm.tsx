"use client";

import { StatusBadge } from "./Badge";
import type { SaveState } from "@/lib/useAutosave";

export const SECTIONS = [
  { key: "inefficiency", title: "1. Inefficiency identification", hint: "What is inefficient? Where is the bottleneck? Why does it perform poorly and what is the consequence?" },
  { key: "approach", title: "2. Optimization approach", hint: "What did you change and which technique did you use? Why is it better, and how is the original behaviour preserved?" },
  { key: "complexity", title: "3. Complexity analysis", hint: "Original and optimized time complexity, original and optimized space complexity, and your assumptions." },
  { key: "tradeoffs", title: "4. Trade-offs and reasoning", hint: "Memory vs runtime, simplicity vs performance, preprocessing cost, data-structure choices, other compromises." },
] as const;
export type SectionKey = (typeof SECTIONS)[number]["key"];
export type ReportValue = Record<SectionKey, string>;
export type EvaluationState = "PENDING" | "DELAYED" | "COMPLETE" | null | undefined;
// What the participant is told once a report is submitted. HTTP success only means "saved": these say what evaluation has actually done.
export const EVALUATION_NOTES: Record<"PENDING" | "DELAYED" | "COMPLETE", string> = {
  PENDING: "Your report is submitted. Automatic evaluation is queued or running.",
  DELAYED: "Your report is submitted and safe, but automatic evaluation did not finish. The organisers will retry it — you do not need to resubmit.",
  COMPLETE: "Your report is submitted and has been evaluated. Marks are released by the organisers after the round.",
};
export const STEPS = ["DRAFT", "SUBMITTED", "EVALUATION_PENDING", "EVALUATED", "REVIEWED"] as const;

export function ReportForm({ value, onChange, max, min, status, evaluation, saveState, saveError, onSubmit, onAmend, busy, error, canEdit }: {
  value: ReportValue; onChange: (v: ReportValue) => void; max: number; min: number; status: string; evaluation?: EvaluationState; saveState: SaveState; saveError?: string | null;
  onSubmit: () => void; onAmend: () => void; busy: boolean; error: string | null; canEdit: boolean;
}) {
  const locked = status !== "DRAFT";
  const short = SECTIONS.filter((s) => value[s.key].trim().length < min).map((s) => s.key);
  const saveText = { idle: "", dirty: "Unsaved changes…", saving: "Saving…", saved: "All changes saved", error: `Could not save${saveError ? `: ${saveError}` : ""}` }[saveState];
  return (
    <div className="space-y-4" data-testid="report-form">
      <ol className="flex flex-wrap gap-2 text-xs" aria-label="Report status">
        {STEPS.map((s) => <li key={s} className={STEPS.indexOf(s) <= STEPS.indexOf(status as (typeof STEPS)[number]) ? "" : "opacity-40"}>
          <StatusBadge status={s === "EVALUATION_PENDING" && evaluation === "DELAYED" ? "EVALUATION_DELAYED" : s} /></li>)}
      </ol>
      {locked && evaluation && (
        <p role="status" data-testid="evaluation-status" data-state={evaluation} className={`rounded-md border px-3 py-2 text-sm ${evaluation === "DELAYED" ? "border-danger/60 text-danger" : "border-line text-muted"}`}>
          {EVALUATION_NOTES[evaluation]}
        </p>
      )}
      {SECTIONS.map((s) => {
        const len = value[s.key].length;
        const tooShort = !locked && short.includes(s.key) && len > 0;
        return (
          <div key={s.key}>
            <label htmlFor={`rep-${s.key}`} className="!text-sm !text-fg">{s.title}</label>
            <p className="mb-1 text-xs text-muted">{s.hint}</p>
            <textarea id={`rep-${s.key}`} rows={5} value={value[s.key]} maxLength={max} readOnly={locked || !canEdit}
              onChange={(e) => onChange({ ...value, [s.key]: e.target.value })} aria-describedby={`rep-${s.key}-meta`} />
            <p id={`rep-${s.key}-meta`} className={`mt-1 text-xs ${tooShort ? "text-danger" : "text-muted"}`}>
              {len}/{max}{tooShort ? ` — at least ${min} characters needed to submit` : ""}
            </p>
          </div>
        );
      })}
      <div className="flex flex-wrap items-center gap-3">
        {!locked && (
          <button type="button" disabled={busy || short.length > 0 || !canEdit} onClick={onSubmit}
            className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-strong disabled:opacity-50">Submit report</button>
        )}
        {locked && canEdit && (
          <button type="button" disabled={busy} onClick={onAmend} className="rounded-md border border-line px-3 py-1.5 text-sm hover:bg-surface2 disabled:opacity-50">Create amendment (new version)</button>
        )}
        <span className={`text-xs ${saveState === "error" ? "text-danger" : "text-muted"}`} role="status">{locked ? "Submitted — this version can no longer be edited." : saveText}</span>
      </div>
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
    </div>
  );
}
