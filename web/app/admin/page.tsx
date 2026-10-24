"use client";

import Link from "next/link";
import { Card } from "@/components/ui";
import { useLoad } from "@/lib/useLoad";

type Matrix = { round_state: string; locked: boolean; problems: string[]; teams: { id: string; complete: boolean; member_count: number }[] };

export default function AdminHome() {
  const { data, error } = useLoad<Matrix>("/admin/assignments");
  const teams = data?.teams ?? [];
  const stat = (label: string, value: string | number) => (
    <div className="rounded-lg border border-line bg-surface p-4">
      <div className="text-2xl font-semibold">{value}</div>
      <div className="text-xs text-muted">{label}</div>
    </div>
  );
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Admin overview</h1>
      {error && <p role="alert" className="text-danger">{error}</p>}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        {stat("Teams", teams.length)}
        {stat("Eligible (2+ members)", teams.filter((t) => t.member_count >= 2).length)}
        {stat("Fully assigned", teams.filter((t) => t.complete).length)}
        {stat("Round 1", data ? (data.locked ? `${data.round_state} · locked` : data.round_state) : "…")}
      </div>
      <Card title="Set-up checklist">
        <ol className="list-decimal space-y-1 pl-5 text-sm text-muted">
          <li><Link className="text-accent" href="/admin/teams">Create teams</Link>, add 2–3 members and participant accounts.</li>
          <li><Link className="text-accent" href="/admin/questions">Create and publish questions</Link> with variants.</li>
          <li><Link className="text-accent" href="/admin/assignments">Assign one DSA, OOP and DBMS variant</Link> to every team, then start Round 1.</li>
        </ol>
      </Card>
    </div>
  );
}
