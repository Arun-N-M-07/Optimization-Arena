"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { Button, Card, ErrorNote } from "@/components/ui";
import { errText, useLoad } from "@/lib/useLoad";

const CATS = ["DSA", "OOP", "DBMS"] as const;
type Cell = { variant_id: string; label: string; title: string; locked: boolean } | null;
type Matrix = {
  round_state: string; locked: boolean; problems: string[];
  teams: { id: string; team_number: number; name: string; is_active: boolean; member_count: number; complete: boolean; assignments: Record<string, Cell> }[];
};
type Question = { id: string; category: string; title: string; status: string; variants: { id: string; label: string; status: string }[] };

export default function AssignmentsPage() {
  const m = useLoad<Matrix>("/admin/assignments");
  const qs = useLoad<Question[]>("/admin/questions");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(fn: () => Promise<unknown>) {
    setMsg(null);
    setBusy(true);
    try { await fn(); } catch (e) { setMsg(errText(e)); }
    await m.reload();
    setBusy(false);
  }
  const options = (cat: string) =>
    (qs.data ?? []).filter((q) => q.category === cat && q.status === "PUBLISHED")
      .flatMap((q) => q.variants.filter((v) => v.status === "PUBLISHED").map((v) => ({ id: v.id, text: `${q.title} — ${v.label}` })));
  const editable = m.data && ["DRAFT", "SCHEDULED"].includes(m.data.round_state);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">Assignments</h1>
        {m.data && <span className="text-sm text-muted">Round 1: {m.data.round_state}{m.data.locked ? " · locked" : ""}</span>}
      </div>
      <ErrorNote message={msg ?? m.error ?? qs.error} />
      <div className="overflow-x-auto rounded-lg border border-line bg-surface">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-line text-xs text-muted uppercase">
            <tr><th className="px-4 py-3">Team</th><th className="px-4 py-3">Members</th>{CATS.map((c) => <th key={c} className="px-4 py-3">{c}</th>)}</tr>
          </thead>
          <tbody>
            {m.data?.teams.map((t) => (
              <tr key={t.id} className="border-b border-line/60 last:border-0">
                <td className="px-4 py-3 font-medium">#{t.team_number} {t.name}</td>
                <td className={`px-4 py-3 ${t.member_count < 2 ? "text-danger" : ""}`}>{t.member_count}</td>
                {CATS.map((cat) => {
                  const cell = t.assignments[cat];
                  return (
                    <td key={cat} className="px-4 py-3">
                      <select aria-label={`${cat} for team ${t.team_number}`} disabled={busy || !editable || !t.is_active} value={cell?.variant_id ?? ""}
                        onChange={(e) => e.target.value
                          ? run(() => api(`/admin/teams/${t.id}/assignments/${cat}`, { method: "PUT", body: JSON.stringify({ variant_id: e.target.value }) }))
                          : run(() => api(`/admin/teams/${t.id}/assignments/${cat}`, { method: "DELETE" }))}>
                        <option value="">— unassigned —</option>
                        {options(cat).map((o) => <option key={o.id} value={o.id}>{o.text}</option>)}
                      </select>
                      {cell?.locked && <span className="text-xs text-muted">locked</span>}
                    </td>
                  );
                })}
              </tr>
            ))}
            {m.data?.teams.length === 0 && <tr><td className="px-4 py-6 text-muted" colSpan={5}>Create teams first.</td></tr>}
          </tbody>
        </table>
      </div>
      {m.data && m.data.problems.length > 0 && editable && (
        <Card title="Blocking issues">
          <ul className="list-disc space-y-1 pl-5 text-sm text-muted">{m.data.problems.map((p) => <li key={p}>{p}</li>)}</ul>
        </Card>
      )}
      {editable && (
        <div className="flex gap-3">
          <Button variant="ghost" disabled={busy} onClick={() => run(() => api("/admin/assignments/lock", { method: "POST" }))}>Lock assignments</Button>
          <Button disabled={busy} onClick={() => { if (confirm("Start Round 1 now? Assignments will be locked.")) run(() => api("/admin/rounds/1/start", { method: "POST", body: JSON.stringify({ duration_minutes: 150 }) })); }}>Start Round 1</Button>
        </div>
      )}
    </div>
  );
}
