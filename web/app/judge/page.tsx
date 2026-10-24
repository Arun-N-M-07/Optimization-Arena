"use client";

import Link from "next/link";
import { useState } from "react";
import { StatusBadge } from "@/components/arena/Badge";
import { useLoad } from "@/lib/useLoad";

type Item = { report_id: string; version: number; report_status: string; team_number: number; team_name: string; title: string; category: string;
  ai_status: string | null; needs_review: boolean | null; approved: boolean; submitted_at: string };

export default function JudgeHome() {
  const { data, error } = useLoad<{ items: Item[] }>("/judge/queue");
  const [filter, setFilter] = useState<"todo" | "all">("todo");
  if (error) return <p role="alert" className="text-danger">{error}</p>;
  if (!data) return <p className="text-muted">Loading…</p>;
  const items = data.items.filter((i) => filter === "all" || !i.approved);
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between"><h1 className="text-2xl font-semibold tracking-tight">Review queue</h1>
        <div className="flex gap-1 text-sm">{(["todo", "all"] as const).map((f) => <button key={f} onClick={() => setFilter(f)} className={`rounded px-3 py-1 ${filter === f ? "bg-surface2" : "text-muted"}`}>{f === "todo" ? "To review" : "All"}</button>)}</div></div>
      {items.length === 0 ? <p className="text-sm text-muted">{data.items.length === 0 ? "Nothing is assigned to you yet, or no reports have been submitted." : "Everything assigned to you has been approved."}</p> : (
        <div className="overflow-x-auto rounded-lg border border-line bg-surface"><table className="w-full text-left text-sm">
          <thead className="border-b border-line text-xs text-muted uppercase"><tr><th className="px-4 py-3">Team</th><th className="px-4 py-3">Question</th><th className="px-4 py-3">AI evaluation</th><th className="px-4 py-3">Status</th><th /></tr></thead>
          <tbody>{items.map((i) => (
            <tr key={i.report_id} className="border-b border-line/60 last:border-0">
              <td className="px-4 py-3">#{i.team_number} {i.team_name}</td><td className="px-4 py-3">{i.category} · {i.title}</td>
              <td className="px-4 py-3"><StatusBadge status={i.ai_status ?? "PENDING"} />{i.needs_review && <span className="ml-2 text-xs text-amber-300">flagged</span>}</td>
              <td className="px-4 py-3">{i.approved ? <StatusBadge status="REVIEWED" /> : <StatusBadge status={i.report_status} />}</td>
              <td className="px-4 py-3"><Link className="text-accent" href={`/judge/reports/${i.report_id}`}>Review</Link></td></tr>))}</tbody></table></div>
      )}
    </div>
  );
}
