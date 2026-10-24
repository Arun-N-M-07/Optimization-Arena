"use client";

import { useState } from "react";
import { Button, Card, ErrorNote } from "@/components/ui";
import { api } from "@/lib/api";
import { errText, useLoad } from "@/lib/useLoad";

type T = { id: string; team_number: number; name: string; is_finalist: boolean; members: number; round1_total: number; rank: number | null; reports_reviewed: number; reports_total: number };
type F = { locked: boolean; round1_state: string; teams: T[] };

export default function Finalists() {
  const { data, error, reload } = useLoad<F>("/admin/finalists");
  const [edited, setSel] = useState<Set<string> | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function act(fn: () => Promise<unknown>) { setMsg(null); setBusy(true); try { await fn(); } catch (e) { setMsg(errText(e)); } await reload(); setBusy(false); }
  if (!data) return <p className="text-muted">{error ?? "Loading…"}</p>;
  const sel = edited ?? new Set(data.teams.filter((t) => t.is_finalist).map((t) => t.id));
  const ended = ["ENDED", "RESULTS_PUBLISHED"].includes(data.round1_state);
  const sorted = [...data.teams].sort((a, b) => (a.rank ?? 999) - (b.rank ?? 999));
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Finalists</h1>
      {!ended && <p role="note" className="text-sm text-amber-300">Round 1 must have ended before finalists can be selected (currently {data.round1_state}).</p>}
      <Card title="Round 1 standings" action={<span className="text-xs text-muted">{data.locked ? "Locked" : `${sel.size} selected`}</span>}>
        <table className="w-full text-left text-sm"><thead className="text-xs text-muted uppercase"><tr><th className="py-2 w-10" /><th>Rank</th><th>Team</th><th>Members</th><th>Reports approved</th><th>Round 1 total</th></tr></thead>
          <tbody>{sorted.map((t) => (
            <tr key={t.id} className="border-t border-line/60"><td className="py-2"><input type="checkbox" aria-label={`Select team ${t.team_number}`} className="!w-auto" disabled={busy || data.locked || !ended} checked={sel.has(t.id)}
              onChange={(e) => { const n = new Set(sel); if (e.target.checked) n.add(t.id); else n.delete(t.id); setSel(n); }} /></td>
              <td>{t.rank ?? "—"}</td><td>#{t.team_number} {t.name}</td><td>{t.members}</td><td>{t.reports_reviewed}/{t.reports_total}</td><td>{t.round1_total}</td></tr>))}</tbody></table>
        {!data.locked && <div className="mt-4 flex gap-3">
          <Button disabled={busy || !ended} onClick={() => act(() => api("/admin/finalists", { method: "PUT", body: JSON.stringify({ team_ids: [...sel] }) }))}>Save selection</Button>
          <Button variant="ghost" disabled={busy || !ended} onClick={() => { if (confirm("Lock finalists? This cannot be undone.")) void act(() => api("/admin/finalists/lock", { method: "POST" })); }}>Lock finalists</Button></div>}
        <div className="mt-2"><ErrorNote message={msg ?? error} /></div>
        <p className="mt-3 text-xs text-muted">Finalists keep their Round 1 team numbers. Select teams, save, then lock before starting Round 2.</p>
      </Card>
    </div>
  );
}
