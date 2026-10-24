"use client";

import Link from "next/link";
import { useCallback, useEffect } from "react";
import { StatusBadge } from "./Badge";
import { Countdown } from "./Countdown";
import { LiveDot } from "./LiveDot";
import { Card } from "@/components/ui";
import { useServerClock } from "@/lib/useClock";
import { useLoad } from "@/lib/useLoad";
import { useRealtimeRefetch } from "@/lib/useRealtime";

type Q = { round: number; category: string; title: string; difficulty: string; variant_id: string; label: string; languages: string[]; finals: number; report_status: string | null };
type Resp = { server_now: string; rounds: Record<string, { state: string; ends_at: string | null }>; questions: Q[] };

export function QuestionList({ round }: { round: 1 | 2 }) {
  const { data, error, reload } = useLoad<Resp>("/participant/questions");
  const clock = useServerClock();
  useEffect(() => clock.sync(data?.server_now), [data, clock]);
  const live = useRealtimeRefetch(useCallback(() => void reload(), [reload]));
  if (error) return <p role="alert" className="text-danger">{error}</p>;
  if (!data) return <p className="text-muted">Loading…</p>;
  const s = data.rounds[String(round)];
  const qs = data.questions.filter((q) => q.round === round);
  const title = round === 1 ? "Round 1 · Legacy Code Autopsy" : "Round 2 · Live Optimization Duel";
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-4">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        <StatusBadge status={s.state} />
        <span className="ml-auto flex items-center gap-4"><LiveDot state={live} /><Countdown endsAt={s.ends_at} now={clock.now} state={s.state} /></span>
      </div>
      {qs.length === 0 ? (
        <Card><p className="text-sm text-muted">{round === 2 ? "Round 2 is open to finalists only, and appears here when it starts." : "Round 1 has not started yet. Your three questions will appear here when it does."}</p></Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-3">
          {qs.map((q) => (
            <Link key={q.variant_id} href={`/participant/round-1/${q.variant_id}`} className="rounded-lg border border-line bg-surface p-5 transition hover:border-accent">
              <p className="text-xs text-accent">{q.category}</p>
              <h2 className="mt-1 font-semibold">{q.title}</h2>
              <p className="mt-1 text-xs text-muted">{q.difficulty} · {q.languages.join(", ")}</p>
              <div className="mt-4 flex flex-wrap items-center gap-2 text-xs">
                <span className="text-muted">{q.finals > 0 ? `${q.finals} submission${q.finals > 1 ? "s" : ""}` : "Not submitted"}</span>
                {round === 1 && <StatusBadge status={q.report_status ?? "DRAFT"} />}
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
