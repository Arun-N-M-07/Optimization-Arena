"use client";

import { useCallback, useEffect, useState } from "react";
import { LiveDot } from "./LiveDot";
import { api } from "@/lib/api";
import { useRealtimeRefetch } from "@/lib/useRealtime";

type Row = { rank: number; team_number: number; name: string; total: number; report?: number; code?: number; manual?: number; round1_total?: number; round2_total?: number };
type Board = { published: boolean; rows: Row[]; note?: string };
type State = { server_now: string; rounds: Record<string, { state: string; results_published: boolean }>; announcements: { id: string; message: string }[] };
const TABS = [["1", "Round 1"], ["2", "Round 2"], ["final", "Combined"]] as const;

export function PublicBoard({ projector = false }: { projector?: boolean }) {
  const [chosen, setTab] = useState<"1" | "2" | "final" | null>(null);
  const [board, setBoard] = useState<Board | null>(null);
  const [state, setState] = useState<State | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const tab = chosen ?? (state?.rounds["2"]?.results_published ? "2" : "1");

  const refetch = useCallback(async () => {
    try {
      const [s, b] = await Promise.all([api<State>("/public/state"), api<Board>(`/public/leaderboard?round=${tab}`)]);
      setState(s); setBoard(b); setErr(null);
    } catch { setErr("Could not refresh — showing the last known results."); }
  }, [tab]);

  // eslint-disable-next-line react-hooks/set-state-in-effect -- async fetch; state is set after the await
  useEffect(() => { void refetch(); }, [refetch]);
  const live = useRealtimeRefetch(() => void refetch(), ["contest_sessions", "contest_announcements"], 10000);
  const big = projector;
  const cell = big ? "px-6 py-4 text-3xl" : "px-4 py-3 text-sm";
  return (
    <div className={big ? "mx-auto w-full max-w-7xl px-8 py-8" : ""}>
      <div className="mb-6 flex flex-wrap items-center gap-4">
        <h1 className={`font-semibold tracking-tight ${big ? "text-5xl" : "text-2xl"}`}>{projector ? "The Optimization Arena" : "Leaderboard"}</h1>
        <div role="tablist" className="flex gap-1">
          {TABS.map(([k, label]) => <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
            className={`rounded px-3 py-1 ${big ? "text-xl" : "text-sm"} ${tab === k ? "bg-surface2" : "text-muted"}`}>{label}</button>)}</div>
        <span className="ml-auto flex items-center gap-4"><LiveDot state={live} />
          {projector && <button onClick={() => void document.documentElement.requestFullscreen?.()} className="rounded border border-line px-3 py-1 text-sm text-muted hover:text-fg">Full screen</button>}</span>
      </div>
      {state?.announcements[0] && <p role="note" className={`mb-6 rounded-md border border-accent/40 bg-accent/10 px-5 py-3 ${big ? "text-2xl" : "text-sm"}`}>📣 {state.announcements[0].message}</p>}
      {err && <p role="alert" className="mb-3 text-sm text-amber-300">{err}</p>}
      {!board ? <p className="text-muted">Loading…</p> : !board.published ? (
        <p className={`rounded-lg border border-line bg-surface p-8 text-muted ${big ? "text-3xl" : ""}`}>{board.note ?? "Results have not been published yet."}</p>
      ) : (
        <div className="overflow-hidden rounded-lg border border-line bg-surface"><table className="w-full text-left" aria-label="Leaderboard">
          <thead className={`border-b border-line text-muted uppercase ${big ? "text-lg" : "text-xs"}`}><tr><th className={cell}>Rank</th><th className={cell}>Team</th>
            {tab === "final" ? <><th className={cell}>Round 1</th><th className={cell}>Round 2</th></> : null}<th className={`${cell} text-right`}>Score</th></tr></thead>
          <tbody>{board.rows.map((r) => <tr key={r.team_number} className="border-b border-line/60 last:border-0">
            <td className={`${cell} font-mono ${r.rank === 1 ? "text-accent" : ""}`}>{r.rank}</td><td className={cell}><span className="text-muted">#{r.team_number}</span> {r.name}</td>
            {tab === "final" ? <><td className={cell}>{r.round1_total}</td><td className={cell}>{r.round2_total}</td></> : null}<td className={`${cell} text-right font-mono font-semibold`}>{r.total}</td></tr>)}
            {board.rows.length === 0 && <tr><td colSpan={5} className={`${cell} text-muted`}>No teams to show.</td></tr>}</tbody></table></div>
      )}
    </div>
  );
}
