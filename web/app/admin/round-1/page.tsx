"use client";

import Link from "next/link";
import { useState } from "react";
import { StatusBadge } from "@/components/arena/Badge";
import { RoundControls, type RoundInfo } from "@/components/arena/RoundControls";
import { Button, Card, ErrorNote } from "@/components/ui";
import { api, downloadCsv } from "@/lib/api";
import { errText, useLoad } from "@/lib/useLoad";

type Sub = { team_number: number; team_name: string; title: string; category: string; label: string; finals: number; drafts: number; last_final_at: string | null; outcome: string | null; provider: string | null; report_status: string | null };
type Ev = { report_id: string; team_number: number; title: string; report_status: string; ai_status: string | null; attempts: number | null; error: string | null; needs_review: boolean | null; approved: boolean };

export default function Round1Admin() {
  const rounds = useLoad<RoundInfo[]>("/admin/rounds");
  const subs = useLoad<Sub[]>("/admin/submissions?round=1");
  const evs = useLoad<Ev[]>("/admin/evaluations");
  const [msg, setMsg] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const r1 = rounds.data?.[0];
  const refresh = () => { void rounds.reload(); void subs.reload(); void evs.reload(); };
  async function act(fn: () => Promise<unknown>) { setMsg(null); setNote(null); try { await fn(); refresh(); } catch (e) { setMsg(errText(e)); } }
  // One press evaluates a bounded batch inside the request time limit; say plainly when more is waiting so nobody assumes it finished.
  async function runPending() {
    setMsg(null); setNote(null);
    try {
      const r = await api<{ counts: Record<string, number>; waiting: number }>("/admin/evaluations/run-pending", { method: "POST" });
      const tried = Object.entries(r.counts).reduce((a, [k, n]) => a + (k === "SKIPPED" ? 0 : n), 0);
      setNote(tried === 0 && r.waiting === 0 ? "Nothing is waiting for evaluation."
        : `Attempted ${tried}: ${r.counts.COMPLETED ?? 0} completed${r.counts.FAILED ? `, ${r.counts.FAILED} failed (still retryable)` : ""}.${r.waiting ? ` ${r.waiting} more still waiting — press again.` : ""}`);
      refresh();
    } catch (e) { setMsg(errText(e)); }
  }
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between"><h1 className="text-2xl font-semibold tracking-tight">Round 1 operations</h1><Button variant="ghost" onClick={refresh}>Refresh</Button></div>
      {r1 && <RoundControls info={r1} onChange={refresh} startAction={() => api("/admin/rounds/1/start", { method: "POST", body: JSON.stringify({ duration_minutes: 150 }) })} />}
      <ErrorNote message={msg ?? rounds.error} />
      {r1 && ["DRAFT", "SCHEDULED"].includes(r1.state) && <p className="text-sm text-muted">Assign questions on the <Link className="text-accent" href="/admin/assignments">Assignments</Link> page first; starting locks them.</p>}
      <Card title="Submission monitor" action={<Button variant="ghost" onClick={() => void downloadCsv("/admin/export/submissions.csv?round=1", "submissions-round-1.csv")}>Export CSV</Button>}>
        <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead className="text-xs text-muted uppercase"><tr><th className="py-2">Team</th><th>Question</th><th>Finals</th><th>Last result</th><th>Report</th></tr></thead>
          <tbody>{subs.data?.map((s, i) => <tr key={i} className="border-t border-line/60"><td className="py-2">#{s.team_number}</td><td>{s.category} · {s.title} ({s.label})</td><td>{s.finals}</td>
            <td><StatusBadge status={s.provider === "mock" ? "MOCK" : s.outcome} /></td><td><StatusBadge status={s.report_status} /></td></tr>)}
            {subs.data?.length === 0 && <tr><td colSpan={5} className="py-3 text-muted">No assignments yet.</td></tr>}</tbody></table></div>
      </Card>
      <Card title="Report evaluations" action={<Button variant="ghost" onClick={() => void runPending()}>Run pending now</Button>}>
        {note && <p role="status" className="mb-3 text-sm text-muted">{note}</p>}
        <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead className="text-xs text-muted uppercase"><tr><th className="py-2">Team</th><th>Question</th><th>AI</th><th>Attempts</th><th>Judge</th><th /></tr></thead>
          <tbody>{evs.data?.map((e) => <tr key={e.report_id} className="border-t border-line/60"><td className="py-2">#{e.team_number}</td><td>{e.title}</td>
            <td><StatusBadge status={e.ai_status ?? "PENDING"} />{e.needs_review && <span className="ml-1 text-xs text-amber-300">flagged</span>}{e.error && <div className="text-xs text-danger">{e.error}</div>}</td>
            <td>{e.attempts ?? 0}</td><td>{e.approved ? <StatusBadge status="REVIEWED" /> : <span className="text-xs text-muted">awaiting approval</span>}</td>
            <td><Button variant="ghost" onClick={() => act(() => api(`/admin/reports/${e.report_id}/evaluate`, { method: "POST" }))}>{e.ai_status === "COMPLETED" ? "Re-check" : "Retry"}</Button></td></tr>)}
            {evs.data?.length === 0 && <tr><td colSpan={6} className="py-3 text-muted">No reports submitted yet.</td></tr>}</tbody></table></div>
        <p className="mt-3 text-xs text-muted">Judges approve marks from the <b>Judge</b> area. Admins may also review any report via the same screen at /judge.</p>
      </Card>
    </div>
  );
}
