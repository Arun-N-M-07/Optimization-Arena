"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { StatusBadge } from "@/components/arena/Badge";
import { Button, Card, ErrorNote } from "@/components/ui";
import { api } from "@/lib/api";
import { errText, useLoad } from "@/lib/useLoad";

const CRIT = ["INEFFICIENCY", "APPROACH", "COMPLEXITY", "TRADEOFFS"] as const;
type Crit = { criterion: string; marks: number; max_marks: number; explanation: string; evidence: string | null };
type Ev = { id: string; source: string; status: string; model: string | null; needs_review: boolean; summary: string | null; comment: string | null;
  approved_at: string | null; total: number; criteria: Crit[]; error: string | null; created_at: string };
type Detail = { id: string; team_number: number; team_name: string; title: string; category: string; version: number; status: string;
  description: string; expected_behavior: string; original_code: Record<string, string>; reference_concepts: string | null; expected_complexity: string | null;
  inefficiency: string; approach: string; complexity: string; tradeoffs: string;
  submission: { language: string; code: string; outcome: string | null; provider: string | null; safe_message: string | null } | null;
  evaluations: Ev[]; history: { created_at: string; criterion: string; previous_marks: number; new_marks: number; reason: string; by: string }[] };

export default function ReviewPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data, error, reload } = useLoad<Detail>(`/judge/reports/${id}`);
  const [marks, setMarks] = useState<Record<string, string>>({});
  const [why, setWhy] = useState<Record<string, string>>({});
  const [comment, setComment] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const ai = data?.evaluations.find((e) => e.source === "AI" && e.status === "COMPLETED");
  const lastJudge = [...(data?.evaluations ?? [])].reverse().find((e) => e.source === "JUDGE");

  useEffect(() => {
    const src = lastJudge ?? ai;
    if (!src) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setMarks(Object.fromEntries(src.criteria.map((c) => [c.criterion, String(c.marks)])));
    setWhy(Object.fromEntries(src.criteria.map((c) => [c.criterion, c.explanation])));
    setComment(lastJudge?.comment ?? "");
  }, [ai?.id, lastJudge?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function save(approve: boolean) {
    setBusy(true); setMsg(null);
    try {
      const criteria = CRIT.map((c) => ({ criterion: c, marks: Number(marks[c] ?? 0), explanation: why[c] ?? "" }));
      await api(`/judge/reports/${id}/review`, { method: "POST", body: JSON.stringify({ criteria, comment, approve }) });
      setMsg(approve ? "Approved. These marks are now official." : "Saved as a draft review (not official yet).");
      await reload();
    } catch (e) { setMsg(errText(e)); } finally { setBusy(false); }
  }
  if (error) return <div><p role="alert" className="text-danger">{error}</p><Link className="text-accent" href="/judge">← Queue</Link></div>;
  if (!data) return <p className="text-muted">Loading…</p>;
  const total = CRIT.reduce((a, c) => a + (Number(marks[c]) || 0), 0);
  const mock = data.submission?.provider === "mock";
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3"><Link className="text-sm text-muted" href="/judge">← Queue</Link>
        <h1 className="text-xl font-semibold tracking-tight">Team {data.team_number} · {data.category} · {data.title}</h1><StatusBadge status={data.status} /><span className="text-xs text-muted">report v{data.version}</span></div>
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="space-y-4">
          <Card title="Question"><p className="mb-2 whitespace-pre-wrap text-sm">{data.description}</p><p className="text-xs text-muted">Expected: {data.expected_behavior}</p>
            {(data.expected_complexity || data.reference_concepts) && <p className="mt-2 text-xs text-muted">Evaluator notes — complexity: {data.expected_complexity || "—"}; concepts: {data.reference_concepts || "—"}</p>}</Card>
          <Card title="Original code"><pre className="overflow-x-auto rounded bg-surface2 p-3 font-mono text-xs">{Object.values(data.original_code)[0]}</pre></Card>
          <Card title="Submitted code" action={data.submission && <span className="text-xs text-muted">{data.submission.language}</span>}>
            {data.submission ? <><pre className="overflow-x-auto rounded bg-surface2 p-3 font-mono text-xs">{data.submission.code}</pre>
              <div className="mt-2 flex items-center gap-2 text-xs"><StatusBadge status={mock ? "MOCK" : data.submission.outcome} /><span className="text-muted">{data.submission.safe_message}</span></div></> : <p className="text-sm text-muted">No code attached.</p>}</Card>
        </div>
        <div className="space-y-4">
          <Card title="Autopsy report">{(["inefficiency", "approach", "complexity", "tradeoffs"] as const).map((k) => (
            <div key={k} className="mb-3"><h3 className="text-xs font-semibold text-muted uppercase">{k}</h3><p className="whitespace-pre-wrap text-sm">{data[k]}</p></div>))}</Card>
          <Card title="AI assessment" action={ai && <span className="text-xs text-muted">{ai.model} · {ai.total}/20</span>}>
            {!ai ? <p className="text-sm text-muted">{data.evaluations.find((e) => e.source === "AI")?.error ?? "No AI evaluation yet."}</p> : <>
              {ai.needs_review && <p className="mb-2 text-xs text-amber-300">Flagged for human review.</p>}
              {ai.summary && <p className="mb-3 text-sm">{ai.summary}</p>}
              <ul className="space-y-2 text-sm">{ai.criteria.map((c) => <li key={c.criterion}><b>{c.criterion}</b> {c.marks}/{c.max_marks} — <span className="text-muted">{c.explanation}</span></li>)}</ul></>}
          </Card>
        </div>
      </div>
      <Card title="Your marks (official once approved)" action={<span className="text-sm">{total} / 20</span>}>
        <div className="grid gap-4 md:grid-cols-2">{CRIT.map((c) => (
          <div key={c}><label htmlFor={`m-${c}`}>{c} (0–5, steps of 0.5)</label>
            <input id={`m-${c}`} type="number" min={0} max={5} step={0.5} value={marks[c] ?? ""} onChange={(e) => setMarks({ ...marks, [c]: e.target.value })} />
            <label htmlFor={`w-${c}`} className="mt-2">Explanation / reason</label>
            <textarea id={`w-${c}`} rows={2} value={why[c] ?? ""} onChange={(e) => setWhy({ ...why, [c]: e.target.value })} /></div>))}</div>
        <label htmlFor="cmt" className="mt-4">Comment to the team (shown when results are released)</label>
        <textarea id="cmt" rows={2} value={comment} onChange={(e) => setComment(e.target.value)} />
        <div className="mt-4 flex gap-3"><Button disabled={busy} onClick={() => void save(true)}>Approve marks</Button><Button variant="ghost" disabled={busy} onClick={() => void save(false)}>Save without approving</Button></div>
        {msg && <p role="status" className="mt-3 text-sm">{msg}</p>}<ErrorNote message={null} />
      </Card>
      {data.history.length > 0 && <Card title="Override history"><ul className="space-y-1 text-sm">{data.history.map((h, i) => <li key={i} className="text-muted">{h.criterion}: {h.previous_marks} → {h.new_marks} by {h.by} — {h.reason}</li>)}</ul></Card>}
    </div>
  );
}
