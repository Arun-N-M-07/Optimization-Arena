"use client";

import { useState } from "react";
import { Button, Card, ErrorNote } from "@/components/ui";
import { api } from "@/lib/api";
import { errText, useLoad } from "@/lib/useLoad";

type Judge = { id: string; email: string; team_ids: string[]; pending: number };
type Team = { id: string; team_number: number; name: string };
type User = { id: string; email: string; role: string; team_number: number | null };

export default function Judges() {
  const judges = useLoad<Judge[]>("/admin/judges");
  const teams = useLoad<Team[]>("/admin/teams");
  const users = useLoad<User[]>("/admin/users");
  const [edits, setSel] = useState<Record<string, Set<string>>>({});
  const [msg, setMsg] = useState<string | null>(null);
  const [acct, setAcct] = useState({ email: "", password: "" });
  const sel: Record<string, Set<string>> = Object.fromEntries((judges.data ?? []).map((j) => [j.id, edits[j.id] ?? new Set(j.team_ids)]));
  async function act(fn: () => Promise<unknown>, ok: string) { setMsg(null); try { await fn(); setMsg(ok); await judges.reload(); await users.reload(); } catch (e) { setMsg(errText(e)); } }
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Judges</h1>
      <Card title="New judge account">
        <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); void act(async () => { await api("/admin/users", { method: "POST", body: JSON.stringify({ ...acct, role: "JUDGE" }) }); setAcct({ email: "", password: "" }); }, "Judge account created."); }}>
          <div className="min-w-56 flex-1"><label htmlFor="je">Email</label><input id="je" type="email" required value={acct.email} onChange={(e) => setAcct({ ...acct, email: e.target.value })} /></div>
          <div className="min-w-56 flex-1"><label htmlFor="jp">Password (10+ characters)</label><input id="jp" type="password" minLength={10} required autoComplete="new-password" value={acct.password} onChange={(e) => setAcct({ ...acct, password: e.target.value })} /></div>
          <Button type="submit">Create judge</Button></form>
      </Card>
      {msg && <p role="status" className="text-sm">{msg}</p>}<ErrorNote message={judges.error ?? teams.error} />
      {judges.data?.length === 0 && <p className="text-sm text-muted">No judge accounts yet.</p>}
      {judges.data?.map((j) => (
        <Card key={j.id} title={j.email} action={<span className="text-xs text-muted">{j.pending} report(s) awaiting approval</span>}>
          <p className="mb-2 text-xs text-muted">A judge can only see and review the teams ticked here.</p>
          <div className="flex flex-wrap gap-3 text-sm">{teams.data?.map((t) => (
            <label key={t.id} className="flex items-center gap-1 !text-fg"><input type="checkbox" className="!w-auto" checked={sel[j.id]?.has(t.id) ?? false}
              onChange={(e) => { const n = new Set(sel[j.id]); if (e.target.checked) n.add(t.id); else n.delete(t.id); setSel({ ...edits, [j.id]: n }); }} />#{t.team_number}</label>))}</div>
          <Button className="mt-3" onClick={() => void act(() => api(`/admin/judges/${j.id}/teams`, { method: "PUT", body: JSON.stringify({ team_ids: [...(sel[j.id] ?? [])] }) }), "Assignments saved.")}>Save assignments</Button>
        </Card>))}
      <Card title="All accounts"><table className="w-full text-left text-sm"><thead className="text-xs text-muted uppercase"><tr><th className="py-1">Email</th><th>Role</th><th>Team</th></tr></thead>
        <tbody>{users.data?.map((u) => <tr key={u.id} className="border-t border-line/60"><td className="py-2">{u.email}</td><td>{u.role}</td><td>{u.team_number ? `#${u.team_number}` : "—"}</td></tr>)}</tbody></table></Card>
    </div>
  );
}
