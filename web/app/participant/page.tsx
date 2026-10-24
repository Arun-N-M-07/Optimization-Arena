"use client";

import Link from "next/link";
import { useCallback, useEffect } from "react";
import { StatusBadge } from "@/components/arena/Badge";
import { Countdown } from "@/components/arena/Countdown";
import { LiveDot } from "@/components/arena/LiveDot";
import { Card } from "@/components/ui";
import { useServerClock } from "@/lib/useClock";
import { useLoad } from "@/lib/useLoad";
import { useRealtimeRefetch } from "@/lib/useRealtime";

type Team = { team_number: number; name: string; is_finalist: boolean; members: { id: string; full_name: string }[] };
type Q = { round: number; category: string; title: string; variant_id: string; finals: number; report_status: string | null };
type Qs = { server_now: string; rounds: Record<string, { state: string; ends_at: string | null }>; questions: Q[] };
type Pub = { announcements: { id: string; message: string; created_at: string }[] };

export default function ParticipantHome() {
  const team = useLoad<Team>("/participant/team");
  const qs = useLoad<Qs>("/participant/questions");
  const pub = useLoad<Pub>("/public/state");
  const clock = useServerClock();
  useEffect(() => clock.sync(qs.data?.server_now), [qs.data, clock]);
  const live = useRealtimeRefetch(useCallback(() => { void qs.reload(); void pub.reload(); }, [qs, pub]));

  if (team.error) return <p role="alert" className="text-danger">{team.error}</p>;
  if (!team.data) return <p className="text-muted">Loading…</p>;
  const r1 = qs.data?.rounds["1"], r2 = qs.data?.rounds["2"];
  const q1 = qs.data?.questions.filter((q) => q.round === 1) ?? [];
  const submitted = q1.filter((q) => q.finals > 0).length;
  const reports = q1.filter((q) => q.report_status && q.report_status !== "DRAFT").length;
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div><p className="text-sm text-muted">Your team</p><h1 className="text-3xl font-semibold tracking-tight">Team {team.data.team_number} · {team.data.name}</h1></div>
        <LiveDot state={live} />
      </div>
      {pub.data?.announcements.slice(0, 3).map((a) => (
        <p key={a.id} role="note" className="rounded-md border border-accent/40 bg-accent/10 px-4 py-2 text-sm">📣 {a.message}</p>
      ))}
      <div className="grid gap-4 md:grid-cols-3">
        <Card title="Round 1 · Legacy Code Autopsy">
          {r1 ? <div className="space-y-2"><StatusBadge status={r1.state} /><div className="text-2xl"><Countdown endsAt={r1.ends_at} now={clock.now} state={r1.state} /></div>
            <p className="text-sm text-muted">{submitted}/{q1.length || 3} solutions · {reports}/{q1.length || 3} reports submitted</p></div> : <p className="text-sm text-muted">…</p>}
          <Link href="/participant/round-1" className="mt-3 inline-block text-sm text-accent">Open questions →</Link>
        </Card>
        <Card title="Round 2 · Live Optimization Duel">
          {team.data.is_finalist ? <>{r2 && <div className="space-y-2"><StatusBadge status={r2.state} /><div className="text-2xl"><Countdown endsAt={r2.ends_at} now={clock.now} state={r2.state} /></div></div>}
            <Link href="/participant/round-2" className="mt-3 inline-block text-sm text-accent">Open Round 2 →</Link></> : <p className="text-sm text-muted">Round 2 is for finalists selected after Round 1.</p>}
        </Card>
        <Card title="Members"><ul className="space-y-1 text-sm">{team.data.members.map((m) => <li key={m.id}>{m.full_name}</li>)}</ul>
          <div className="mt-3 flex gap-4 text-sm"><Link className="text-accent" href="/participant/submissions">History</Link><Link className="text-accent" href="/participant/results">Results</Link></div></Card>
      </div>
    </div>
  );
}
