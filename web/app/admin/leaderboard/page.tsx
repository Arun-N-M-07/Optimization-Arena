"use client";

import { useState } from "react";
import { Button, Card, ErrorNote } from "@/components/ui";
import { api, downloadCsv } from "@/lib/api";
import { errText, useLoad } from "@/lib/useLoad";

type Row = { rank: number; team_id: string; team_number: number; name: string; report: number; reports_reviewed: number; reports_total: number; code: number; manual: number; total: number; round1_total?: number; round2_total?: number };

export default function AdminLeaderboard() {
  const [round, setRound] = useState<"1" | "2" | "final">("1");
  const { data, error, reload } = useLoad<{ rows: Row[] }>(`/admin/leaderboard?round=${round}`);
  const [f, setF] = useState({ team_id: "", component: "viva", marks: "", max: "10", reason: "" });
  const [msg, setMsg] = useState<string | null>(null);
  async function addScore(e: React.FormEvent) {
    e.preventDefault(); setMsg(null);
    try {
      await api(`/admin/teams/${f.team_id}/manual-scores`, { method: "PUT", body: JSON.stringify({ round: Number(round === "2" ? 2 : 1), component: f.component, marks: Number(f.marks), max_marks: Number(f.max), reason: f.reason }) });
      setMsg("Score saved and recorded in the audit log."); setF({ ...f, marks: "", reason: "" }); await reload();
    } catch (er) { setMsg(errText(er)); }
  }
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3"><h1 className="text-2xl font-semibold tracking-tight">Leaderboard (private view)</h1>
        <div className="flex items-center gap-2"><div role="tablist" className="flex gap-1 text-sm">{(["1", "2", "final"] as const).map((r) => <button key={r} role="tab" aria-selected={round === r} onClick={() => setRound(r)} className={`rounded px-3 py-1 ${round === r ? "bg-surface2" : "text-muted"}`}>{r === "final" ? "Combined" : `Round ${r}`}</button>)}</div>
          <Button variant="ghost" onClick={() => void downloadCsv(`/admin/export/leaderboard.csv?round=${round}`, `leaderboard-${round}.csv`)}>Export CSV</Button></div></div>
      <p className="text-xs text-muted">Includes unpublished marks. Only judge-approved reports count. Publishing is done from the round pages.</p>
      <ErrorNote message={error} />
      <div className="overflow-x-auto rounded-lg border border-line bg-surface"><table className="w-full text-left text-sm">
        <thead className="border-b border-line text-xs text-muted uppercase"><tr><th className="px-4 py-3">Rank</th><th>Team</th>{round === "final" ? <><th>Round 1</th><th>Round 2</th></> : <><th>Reports</th><th>Code</th><th>Manual</th></>}<th>Total</th></tr></thead>
        <tbody>{data?.rows.map((r) => <tr key={r.team_id} className="border-b border-line/60 last:border-0"><td className="px-4 py-3">{r.rank}</td><td>#{r.team_number} {r.name}</td>
          {round === "final" ? <><td>{r.round1_total}</td><td>{r.round2_total}</td></> : <><td>{r.report} <span className="text-xs text-muted">({r.reports_reviewed}/{r.reports_total} approved)</span></td><td>{r.code}</td><td>{r.manual}</td></>}<td className="font-semibold">{r.total}</td></tr>)}
          {data?.rows.length === 0 && <tr><td colSpan={6} className="px-4 py-4 text-muted">No teams to rank.</td></tr>}</tbody></table></div>
      {round !== "final" && (
        <Card title={`Manual score (Round ${round}) — e.g. viva, bonus`}>
          <form onSubmit={addScore} className="grid gap-3 md:grid-cols-5">
            <div className="md:col-span-2"><label htmlFor="ms-t">Team</label><select id="ms-t" required value={f.team_id} onChange={(e) => setF({ ...f, team_id: e.target.value })}><option value="">—</option>{data?.rows.map((r) => <option key={r.team_id} value={r.team_id}>#{r.team_number} {r.name}</option>)}</select></div>
            <div><label htmlFor="ms-c">Component</label><input id="ms-c" required value={f.component} onChange={(e) => setF({ ...f, component: e.target.value })} /></div>
            <div><label htmlFor="ms-m">Marks</label><input id="ms-m" type="number" min={0} step="0.5" required value={f.marks} onChange={(e) => setF({ ...f, marks: e.target.value })} /></div>
            <div><label htmlFor="ms-x">Out of</label><input id="ms-x" type="number" min={1} required value={f.max} onChange={(e) => setF({ ...f, max: e.target.value })} /></div>
            <div className="md:col-span-4"><label htmlFor="ms-r">Reason (audited)</label><input id="ms-r" required minLength={3} value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} /></div>
            <div className="flex items-end"><Button type="submit">Save score</Button></div></form>
          {msg && <p role="status" className="mt-2 text-sm">{msg}</p>}
        </Card>)}
    </div>
  );
}
