"use client";

import Link from "next/link";
import { useCallback } from "react";
import { StatusBadge } from "@/components/arena/Badge";
import { LiveDot } from "@/components/arena/LiveDot";
import { Card } from "@/components/ui";
import { useLoad } from "@/lib/useLoad";
import { useRealtimeRefetch } from "@/lib/useRealtime";

type Matrix = { teams: { id: string; complete: boolean; member_count: number }[] };
type Round = { round: number; state: string; results_published: boolean };
type Sub = { finals: number; report_status: string | null };
type Ev = { ai_status: string | null; approved: boolean };
type Ops = { database_ms: number; judge_provider: string; judge_is_real: boolean; evaluation_mode: string; gemini_configured: boolean;
  evaluations: { pending: number; failed: number; completed: number; oldest_waiting_seconds: number }; warnings: string[] };

export default function AdminHome() {
  const m = useLoad<Matrix>("/admin/assignments");
  const rounds = useLoad<Round[]>("/admin/rounds");
  const subs = useLoad<Sub[]>("/admin/submissions?round=1");
  const evs = useLoad<Ev[]>("/admin/evaluations");
  const ops = useLoad<Ops>("/admin/ops/status");
  const live = useRealtimeRefetch(useCallback(() => { void rounds.reload(); void subs.reload(); void evs.reload(); void ops.reload(); }, [rounds, subs, evs, ops]), ["contest_sessions", "submissions"]);
  const teams = m.data?.teams ?? [];
  const stat = (label: string, value: string | number) => (
    <div className="rounded-lg border border-line bg-surface p-4"><div className="text-2xl font-semibold">{value}</div><div className="text-xs text-muted">{label}</div></div>);
  const finals = (subs.data ?? []).filter((s) => s.finals > 0).length;
  const pendingEval = (evs.data ?? []).filter((e) => e.ai_status !== "COMPLETED").length;
  const awaiting = (evs.data ?? []).filter((e) => !e.approved).length;
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between"><h1 className="text-2xl font-semibold tracking-tight">Admin overview</h1><LiveDot state={live} /></div>
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        {stat("Teams", teams.length)}{stat("Eligible (2+ members)", teams.filter((t) => t.member_count >= 2).length)}{stat("Fully assigned", teams.filter((t) => t.complete).length)}
        {stat("Questions with a final submission", `${finals}/${subs.data?.length ?? 0}`)}
        {stat("AI evaluations pending/failed", pendingEval)}{stat("Reports awaiting approval", awaiting)}
        <div className="rounded-lg border border-line bg-surface p-4"><StatusBadge status={rounds.data?.[0]?.state ?? "DRAFT"} /><div className="mt-1 text-xs text-muted">Round 1</div></div>
        <div className="rounded-lg border border-line bg-surface p-4"><StatusBadge status={rounds.data?.[1]?.state ?? "DRAFT"} /><div className="mt-1 text-xs text-muted">Round 2</div></div>
      </div>
      <Card title="System status" action={ops.data && <span className="text-xs text-muted">database {ops.data.database_ms} ms</span>}>
        {ops.error && <p role="alert" className="text-sm text-danger">{ops.error}</p>}
        {ops.data && (
          <div className="space-y-3 text-sm">
            <div className="flex flex-wrap gap-x-6 gap-y-1 text-muted">
              <span>Code judge: <b className={ops.data.judge_is_real ? "text-ok" : "text-amber-300"}>{ops.data.judge_provider}{ops.data.judge_is_real ? "" : " (not real)"}</b></span>
              <span>AI evaluation: <b className="text-fg">{ops.data.gemini_configured ? ops.data.evaluation_mode : "not configured"}</b></span>
              <span>Pending {ops.data.evaluations.pending} · failed {ops.data.evaluations.failed} · done {ops.data.evaluations.completed}</span>
            </div>
            {ops.data.warnings.length === 0 ? <p className="text-ok">No warnings.</p> : (
              <ul className="space-y-1">{ops.data.warnings.map((w) => <li key={w} role="status" className="rounded border border-amber-400/40 bg-amber-400/10 px-3 py-1.5 text-amber-200">{w}</li>)}</ul>)}
          </div>)}
      </Card>
      <Card title="Event checklist">
        <ol className="list-decimal space-y-1 pl-5 text-sm text-muted">
          <li><Link className="text-accent" href="/admin/teams">Teams</Link> → add 2–3 members and a participant login for each.</li>
          <li><Link className="text-accent" href="/admin/questions">Questions</Link> → create, add variants, publish. <Link className="text-accent" href="/admin/judges">Judges</Link> → create accounts and assign teams.</li>
          <li><Link className="text-accent" href="/admin/assignments">Assignments</Link> → one DSA, OOP and DBMS variant per team, then start Round 1.</li>
          <li><Link className="text-accent" href="/admin/round-1">Round 1</Link> → monitor, end, then judges approve reports and you publish.</li>
          <li><Link className="text-accent" href="/admin/finalists">Finalists</Link> → <Link className="text-accent" href="/admin/round-2">Round 2</Link> → <Link className="text-accent" href="/admin/leaderboard">Leaderboard</Link> / <Link className="text-accent" href="/projector">Projector</Link>.</li>
        </ol>
      </Card>
    </div>
  );
}
