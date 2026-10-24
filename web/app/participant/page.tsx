"use client";

import Link from "next/link";
import { Card } from "@/components/ui";
import { useLoad } from "@/lib/useLoad";

type Team = { team_number: number; name: string; is_finalist: boolean; members: { id: string; full_name: string }[] };

export default function ParticipantHome() {
  const { data, error } = useLoad<Team>("/participant/team");
  if (error) return <p role="alert" className="text-danger">{error}</p>;
  if (!data) return <p className="text-muted">Loading…</p>;
  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm text-muted">Your team</p>
        <h1 className="text-3xl font-semibold tracking-tight">Team {data.team_number} · {data.name}</h1>
      </div>
      <Card title="Members">
        <ul className="space-y-1 text-sm">{data.members.map((m) => <li key={m.id}>{m.full_name}</li>)}</ul>
      </Card>
      <Link href="/participant/round-1" className="inline-block rounded-md bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-strong">Go to Round 1</Link>
    </div>
  );
}
