"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { Button, Card, ErrorNote } from "@/components/ui";
import { errText, useLoad } from "@/lib/useLoad";

type Member = { id: string; full_name: string; email: string | null };
type Team = { id: string; team_number: number; name: string; member_count: number; eligible: boolean; members: Member[] };

export default function TeamsPage() {
  const { data, error, reload } = useLoad<Team[]>("/admin/teams");
  const [msg, setMsg] = useState<string | null>(null);
  const [num, setNum] = useState("");
  const [name, setName] = useState("");

  async function run(fn: () => Promise<unknown>) {
    setMsg(null);
    try { await fn(); await reload(); } catch (e) { setMsg(errText(e)); }
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Teams</h1>
      <Card title="New team">
        <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); run(async () => { await api("/admin/teams", { method: "POST", body: JSON.stringify({ team_number: Number(num), name }) }); setNum(""); setName(""); }); }}>
          <div className="w-28"><label htmlFor="tn">Team number</label><input id="tn" type="number" min={1} required value={num} onChange={(e) => setNum(e.target.value)} /></div>
          <div className="min-w-56 flex-1"><label htmlFor="tname">Team name</label><input id="tname" required value={name} onChange={(e) => setName(e.target.value)} /></div>
          <Button type="submit">Create team</Button>
        </form>
      </Card>
      <ErrorNote message={msg ?? error} />
      {data?.length === 0 && <p className="text-sm text-muted">No teams yet.</p>}
      <div className="grid gap-4 lg:grid-cols-2">
        {data?.map((t) => <TeamCard key={t.id} team={t} run={run} />)}
      </div>
    </div>
  );
}

function TeamCard({ team, run }: { team: Team; run: (fn: () => Promise<unknown>) => Promise<void> }) {
  const [member, setMember] = useState("");
  const [acct, setAcct] = useState({ email: "", password: "" });
  const [showAcct, setShowAcct] = useState(false);
  return (
    <Card title={`Team ${team.team_number} · ${team.name}`}
      action={<span className={`text-xs ${team.eligible ? "text-ok" : "text-muted"}`}>{team.eligible ? "Eligible" : `Needs 2+ members (${team.member_count})`}</span>}>
      <ul className="mb-3 space-y-1 text-sm">
        {team.members.map((m) => (
          <li key={m.id} className="flex items-center justify-between">
            <span>{m.full_name}</span>
            <Button variant="danger" onClick={() => run(() => api(`/admin/teams/${team.id}/members/${m.id}`, { method: "DELETE" }))}>Remove</Button>
          </li>
        ))}
      </ul>
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); run(async () => { await api(`/admin/teams/${team.id}/members`, { method: "POST", body: JSON.stringify({ full_name: member }) }); setMember(""); }); }}>
        <input aria-label={`New member for team ${team.team_number}`} placeholder="Member name" required value={member} onChange={(e) => setMember(e.target.value)} />
        <Button type="submit" disabled={team.member_count >= 3}>Add</Button>
      </form>
      <button className="mt-3 text-xs text-accent" onClick={() => setShowAcct(!showAcct)}>{showAcct ? "Hide" : "Create participant login"}</button>
      {showAcct && (
        <form className="mt-2 space-y-2" onSubmit={(e) => { e.preventDefault(); run(async () => { await api("/admin/users", { method: "POST", body: JSON.stringify({ ...acct, role: "PARTICIPANT", team_id: team.id }) }); setAcct({ email: "", password: "" }); setShowAcct(false); }); }}>
          <input type="email" placeholder="Email" required value={acct.email} onChange={(e) => setAcct({ ...acct, email: e.target.value })} />
          <input type="password" placeholder="Password (10+ characters)" minLength={10} required autoComplete="new-password" value={acct.password} onChange={(e) => setAcct({ ...acct, password: e.target.value })} />
          <Button type="submit">Create login</Button>
        </form>
      )}
    </Card>
  );
}
