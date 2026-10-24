"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useAutosave } from "@/lib/useAutosave";
import { errText } from "@/lib/useLoad";
import { Button } from "@/components/ui";
import { StatusBadge } from "./Badge";
import { CodeEditor } from "./CodeEditor";
import { ReportForm, type ReportValue } from "./ReportForm";
import { ResultPanel, type RunResult } from "./ResultPanel";

export type Question = {
  round: number; category: string; question_id: string; title: string; difficulty: string; variant_id: string; label: string;
  description: string; expected_behavior: string; constraints: string; languages: string[]; original_code: Record<string, string>;
  visible_tests: { input: string; expected_output: string }[];
};
type Sub = { id: string; kind: string; language: string; code: string; created_at: string; outcome: string | null; passed_visible: number | null;
  total_visible: number | null; passed_hidden: number | null; total_hidden: number | null; runtime_ms: number | null; safe_message: string | null; provider: string | null; is_mock: boolean };
type Report = { id: string; version: number; status: string } & ReportValue;
type ReportResp = { report: Report | null; limits: { max: number; min_to_submit: number } };

const EMPTY: ReportValue = { inefficiency: "", approach: "", complexity: "", tradeoffs: "" };
const SAVE_LABEL = { idle: "", dirty: "Unsaved changes…", saving: "Saving draft…", saved: "Draft saved", error: "Draft not saved" } as const;

export function Workspace({ q, open, showReport }: { q: Question; open: boolean; showReport: boolean }) {
  const [lang, setLang] = useState(q.languages[0]);
  const [code, setCode] = useState(q.original_code[q.languages[0]] ?? "");
  const [loaded, setLoaded] = useState(false);
  const [editorKey, setEditorKey] = useState(0);   // bump to replace the editor's content from outside
  const [tab, setTab] = useState<"problem" | "original" | "history" | "report">("problem");
  const [busy, setBusy] = useState<null | "run" | "submit">(null);
  const [result, setResult] = useState<{ r: RunResult; kind: string } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [history, setHistory] = useState<Sub[]>([]);
  const drafts = useRef<Record<string, string>>({});
  const langRef = useRef(q.languages[0]);
  const base = `/participant/variants/${q.variant_id}`;

  const autosave = useAutosave({
    value: code, enabled: loaded && open,
    save: async (v) => { await api(`${base}/draft`, { method: "PUT", body: JSON.stringify({ language: langRef.current, code: v }) }); drafts.current[langRef.current] = v; },
  });

  const loadHistory = useCallback(async () => {
    try { setHistory((await api<{ submissions: Sub[] }>(`${base}/submissions`)).submissions); } catch (e) { setErr(errText(e)); }
  }, [base]);

  useEffect(() => {
    let alive = true;
    api<{ drafts: Record<string, { code: string }> }>(`${base}/drafts`)
      .then((d) => {
        if (!alive) return;
        for (const [l, v] of Object.entries(d.drafts)) drafts.current[l] = v.code;
        const first = drafts.current[q.languages[0]] ?? q.original_code[q.languages[0]] ?? "";
        setCode(first);
        autosave.reset(first);
        setLoaded(true);
      })
      .catch((e) => { if (alive) { setErr(errText(e)); setLoaded(true); } });
    // eslint-disable-next-line react-hooks/set-state-in-effect -- async fetch; state is set after the await
    void loadHistory();
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [base]);

  async function switchLanguage(next: string) {
    await autosave.flush();
    const content = drafts.current[next] ?? q.original_code[next] ?? "";
    setLang(next);
    langRef.current = next;
    setCode(content);
    setEditorKey((k) => k + 1);
    autosave.reset(content);
  }

  function resetToOriginal() {
    if (!window.confirm("Replace your code with the original implementation? Your current text will be overwritten (it stays in your submission history only if you already submitted it).")) return;
    setCode(q.original_code[lang] ?? "");
    setEditorKey((k) => k + 1);
  }

  async function execute(kind: "run" | "submit") {
    if (kind === "submit" && !window.confirm("Submit this as a final solution? Submissions are permanent; you may still submit again before the deadline.")) return;
    setBusy(kind);
    setErr(null);
    try {
      await autosave.flush();
      const res = await api<{ result: RunResult; duplicate: boolean }>(`${base}/${kind}`, {
        method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() }, body: JSON.stringify({ language: lang, code }),
      });
      setResult({ r: res.result, kind: kind === "run" ? "RUN" : "FINAL" });
      await loadHistory();
    } catch (e) {
      setErr(errText(e));
    } finally {
      setBusy(null);
    }
  }

  const tabs = [["problem", "Problem"], ["original", "Original code"], ["history", `Submissions (${history.filter((h) => h.kind === "FINAL").length})`], ...(showReport ? [["report", "Autopsy Report"]] : [])] as [typeof tab, string][];

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <section className="min-w-0 rounded-lg border border-line bg-surface">
        <div role="tablist" className="flex flex-wrap gap-1 border-b border-line p-2">
          {tabs.map(([k, label]) => (
            <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
              className={`rounded px-3 py-1.5 text-sm ${tab === k ? "bg-surface2 text-fg" : "text-muted hover:text-fg"}`}>{label}</button>
          ))}
        </div>
        <div className="max-h-[78vh] overflow-y-auto p-4" role="tabpanel">
          {tab === "problem" && (
            <div className="space-y-4 text-sm">
              <p className="whitespace-pre-wrap">{q.description}</p>
              <div><h3 className="mb-1 text-xs font-semibold text-muted uppercase">Expected behaviour</h3><p className="whitespace-pre-wrap">{q.expected_behavior}</p></div>
              {q.constraints && <div><h3 className="mb-1 text-xs font-semibold text-muted uppercase">Constraints</h3><p className="whitespace-pre-wrap">{q.constraints}</p></div>}
              {q.visible_tests.length > 0 && (
                <div><h3 className="mb-1 text-xs font-semibold text-muted uppercase">Example tests</h3>
                  {q.visible_tests.map((t, i) => <pre key={i} className="mb-2 rounded bg-surface2 p-2 font-mono text-xs">in:  {t.input}{"\n"}out: {t.expected_output}</pre>)}</div>
              )}
            </div>
          )}
          {tab === "original" && (
            <div><p className="mb-2 text-xs text-muted">The original, working but inefficient implementation ({lang}). Preserve its behaviour.</p>
              <pre className="overflow-x-auto rounded bg-surface2 p-3 font-mono text-xs">{q.original_code[lang]}</pre></div>
          )}
          {tab === "history" && (
            <ul className="space-y-3 text-sm">
              {history.length === 0 && <li className="text-muted">No runs or submissions yet.</li>}
              {history.map((s) => (
                <li key={s.id} className="rounded border border-line p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs text-muted uppercase">{s.kind === "FINAL" ? "Final" : "Run"}</span><span className="font-mono text-xs">{s.language}</span>
                    <StatusBadge status={s.is_mock ? "MOCK" : s.outcome} />
                    <span className="ml-auto text-xs text-muted">{new Date(s.created_at).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata" })}</span>
                  </div>
                  {s.kind === "FINAL" && <button className="mt-2 text-xs text-accent" onClick={() => { setLang(s.language); langRef.current = s.language; setCode(s.code); setEditorKey((k) => k + 1); }}>Load this code into the editor</button>}
                </li>
              ))}
            </ul>
          )}
          {tab === "report" && showReport && <ReportTab q={q} open={open} />}
        </div>
      </section>

      <section className="min-w-0 space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <label htmlFor="lang" className="!mb-0">Language</label>
          <select id="lang" className="!w-auto" value={lang} onChange={(e) => void switchLanguage(e.target.value)} disabled={!loaded}>
            {q.languages.map((l) => <option key={l} value={l}>{l}</option>)}
          </select>
          <button type="button" className="text-xs text-muted hover:text-fg" onClick={resetToOriginal}>Restore starter code</button>
          <span className={`ml-auto text-xs ${autosave.state === "error" ? "text-danger" : "text-muted"}`} role="status" data-testid="save-status">
            {SAVE_LABEL[autosave.state]}{autosave.state === "error" && autosave.error ? `: ${autosave.error}` : ""}
          </span>
        </div>
        {loaded ? <CodeEditor key={`${lang}-${editorKey}`} value={code} onChange={setCode} language={lang} readOnly={!open} /> : <p className="text-sm text-muted">Loading your draft…</p>}
        {!open && <p role="note" className="text-sm text-amber-300">This round is not accepting changes. Your work is read-only.</p>}
        <div className="flex flex-wrap gap-2">
          <Button variant="ghost" disabled={!open || !loaded || busy !== null} onClick={() => void execute("run")}>{busy === "run" ? "Running…" : "Run"}</Button>
          <Button disabled={!open || !loaded || busy !== null} onClick={() => void execute("submit")}>{busy === "submit" ? "Submitting…" : "Submit final solution"}</Button>
        </div>
        {err && <p role="alert" className="text-sm text-danger">{err}</p>}
        <div className="rounded-lg border border-line bg-surface p-4"><ResultPanel result={result?.r ?? null} kind={result?.kind} /></div>
      </section>
    </div>
  );
}

function ReportTab({ q, open }: { q: Question; open: boolean }) {
  const base = `/participant/variants/${q.variant_id}/report`;
  const [value, setValue] = useState<ReportValue>(EMPTY);
  const [meta, setMeta] = useState<{ id?: string; status: string; version: number; max: number; min: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const toValue = (rep: Report | null): ReportValue => rep ? { inefficiency: rep.inefficiency, approach: rep.approach, complexity: rep.complexity, tradeoffs: rep.tradeoffs } : EMPTY;
  const apply = useCallback((r: ReportResp) => {
    const v = toValue(r.report);
    setValue(v);
    setMeta({ id: r.report?.id, status: r.report?.status ?? "DRAFT", version: r.report?.version ?? 1, max: r.limits.max, min: r.limits.min_to_submit });
    return v;
  }, []);
  const load = useCallback(async () => apply(await api<ReportResp>(base)), [apply, base]);

  const autosave = useAutosave<ReportValue>({
    value, enabled: !!meta && meta.status === "DRAFT" && open, delay: 1500,
    save: async (v) => { await api(base, { method: "PUT", body: JSON.stringify(v) }); },
  });
  useEffect(() => {
    // The initial load may only apply while this effect is still current. A late response (slow network, StrictMode
    // double-invoke) must never replace text the participant has since typed — that would then be autosaved as empty.
    let alive = true;
    api<ReportResp>(base)
      .then((r) => { if (alive) autosave.reset(apply(r)); })
      .catch((e) => { if (alive) setErr(errText(e)); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [base]);

  async function submit() {
    if (!window.confirm("Submit this report? A submitted report cannot be edited (you can create a new version while the round is open).")) return;
    setBusy(true); setErr(null);
    try { await autosave.flush(); await api(`${base}/submit`, { method: "POST" }); autosave.reset(await load()); } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  async function amend() {
    setBusy(true); setErr(null);
    try { await api(`${base}/amend`, { method: "POST" }); autosave.reset(await load()); } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  if (!meta) return <p className="text-sm text-muted">{err ?? "Loading report…"}</p>;
  return (
    <div>
      <p className="mb-3 text-xs text-muted">Version {meta.version}. Evaluation marks are released by the organisers after the round.</p>
      <ReportForm value={value} onChange={setValue} max={meta.max} min={meta.min} status={meta.status} saveState={autosave.state} saveError={autosave.error}
        onSubmit={() => void submit()} onAmend={() => void amend()} busy={busy} error={err} canEdit={open} />
    </div>
  );
}
