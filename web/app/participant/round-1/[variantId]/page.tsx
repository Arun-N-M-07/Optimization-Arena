"use client";

import Link from "next/link";
import { use, useCallback, useEffect } from "react";
import { Countdown } from "@/components/arena/Countdown";
import { LiveDot } from "@/components/arena/LiveDot";
import { Workspace, type Question } from "@/components/arena/Workspace";
import { useServerClock } from "@/lib/useClock";
import { useLoad } from "@/lib/useLoad";
import { useRealtimeRefetch } from "@/lib/useRealtime";

type Resp = { server_now: string; rounds: Record<string, { state: string; ends_at: string | null }>; questions: Question[] };

export default function QuestionPage({ params }: { params: Promise<{ variantId: string }> }) {
  const { variantId } = use(params);
  const { data, error, reload } = useLoad<Resp>("/participant/questions");
  const clock = useServerClock();
  useEffect(() => clock.sync(data?.server_now), [data, clock]);
  const live = useRealtimeRefetch(useCallback(() => void reload(), [reload]));
  if (error) return <p role="alert" className="text-danger">{error}</p>;
  if (!data) return <p className="text-muted">Loading…</p>;
  const q = data.questions.find((x) => x.variant_id === variantId);
  if (!q) return <p className="text-muted">Question not available. <Link className="text-accent" href="/participant/round-1">Back to your questions</Link></p>;
  const round = data.rounds[String(q.round)];
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Link href={q.round === 1 ? "/participant/round-1" : "/participant/round-2"} className="text-sm text-muted hover:text-fg">← Questions</Link>
        <h1 className="text-xl font-semibold tracking-tight">{q.category} · {q.title}</h1>
        <span className="text-xs text-muted">{q.difficulty}</span>
        <span className="ml-auto flex items-center gap-4"><LiveDot state={live} /><Countdown endsAt={round.ends_at} now={clock.now} state={round.state} /></span>
      </div>
      <Workspace key={q.variant_id} q={q} open={round.state === "RUNNING"} showReport={q.round === 1} />
    </div>
  );
}
