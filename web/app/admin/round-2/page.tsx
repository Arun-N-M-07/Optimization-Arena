"use client";

import { useEffect, useState } from "react";
import { RoundControls, type RoundInfo } from "@/components/arena/RoundControls";
import { StatusBadge } from "@/components/arena/Badge";
import { Button, Card, ErrorNote } from "@/components/ui";
import { api, downloadCsv } from "@/lib/api";
import { errText, useLoad } from "@/lib/useLoad";

type Q = { id: string; category: string; title: string; status: string; variants: { id: string; label: string; status: string }[] };
type Sub = { team_number: number; finals: number; outcome: string | null; provider: string | null; last_final_at: string | null };

export default function Round2Admin() {
  const rounds = useLoad<RoundInfo[]>("/admin/rounds");
  const qs = useLoad<Q[]>("/admin/questions");
  const subs = useLoad<Sub[]>("/admin/submissions?round=2");
  const [cfg, setCfg] = useState({ variant_id: "", duration_minutes: "60", code_points_per_question: "0", tiebreak: "none", w1: "", w2: "" });
  const [msg, setMsg] = useState<string | null>(null);
  const r2 = rounds.data?.[1];
  useEffect(() => {
    const c = r2?.config as Record<string, unknown> | undefined;
    if (!c) return;
    const f = (c.final ?? {}) as Record<string, number>;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setCfg({ variant_id: String(c.variant_id ?? ""), duration_minutes: String(c.duration_minutes ?? 60), code_points_per_question: String(c.code_points_per_question ?? 0), tiebreak: String(c.tiebreak ?? "none"), w1: f.round1_weight != null ? String(f.round1_weight) : "", w2: f.round2_weight != null ? String(f.round2_weight) : "" });
  }, [r2?.config]);
  const refresh = () => { void rounds.reload(); void subs.reload(); };
  const options = (qs.data ?? []).filter((q) => q.category === "DUEL" && q.status === "PUBLISHED").flatMap((q) => q.variants.filter((v) => v.status === "PUBLISHED").map((v) => ({ id: v.id, text: `${q.title} — ${v.label}` })));
  async function save(e: React.FormEvent) {
    e.preventDefault(); setMsg(null);
    try {
      const body: Record<string, unknown> = { duration_minutes: Number(cfg.duration_minutes), code_points_per_question: Number(cfg.code_points_per_question), tiebreak: cfg.tiebreak };
      if (cfg.variant_id) body.variant_id = cfg.variant_id;
      if (cfg.w1 !== "" && cfg.w2 !== "") body.final = { round1_weight: Number(cfg.w1), round2_weight: Number(cfg.w2) };
      await api("/admin/rounds/2/config", { method: "PUT", body: JSON.stringify(body) });
      setMsg("Saved."); refresh();
    } catch (e2) { setMsg(errText(e2)); }
  }
  const frozen = !!r2 && !["DRAFT", "SCHEDULED"].includes(r2.state);
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Round 2 · Live Optimization Duel</h1>
      {r2 && <RoundControls info={r2} onChange={refresh} startAction={() => api("/admin/rounds/2/start", { method: "POST" })} />}
      <Card title="Configuration">
        <form onSubmit={save} className="grid gap-4 md:grid-cols-2">
          <div className="md:col-span-2"><label htmlFor="rv">Common problem (published DUEL variant)</label>
            <select id="rv" disabled={frozen} value={cfg.variant_id} onChange={(e) => setCfg({ ...cfg, variant_id: e.target.value })}><option value="">— choose —</option>{options.map((o) => <option key={o.id} value={o.id}>{o.text}</option>)}</select>
            {options.length === 0 && <p className="mt-1 text-xs text-muted">Create a DUEL question with a variant on the Questions page and publish both.</p>}</div>
          <div><label htmlFor="rd">Duration (minutes)</label><input id="rd" type="number" min={1} disabled={frozen} value={cfg.duration_minutes} onChange={(e) => setCfg({ ...cfg, duration_minutes: e.target.value })} /></div>
          <div><label htmlFor="rp">Points for an accepted real-judge submission</label><input id="rp" type="number" min={0} value={cfg.code_points_per_question} onChange={(e) => setCfg({ ...cfg, code_points_per_question: e.target.value })} /></div>
          <div><label htmlFor="rt">Tie-break</label><select id="rt" value={cfg.tiebreak} onChange={(e) => setCfg({ ...cfg, tiebreak: e.target.value })}><option value="none">None (tied teams share a rank)</option><option value="earliest_final_submission">Earliest final submission</option></select></div>
          <div className="grid grid-cols-2 gap-2"><div><label htmlFor="w1">Combined: Round 1 weight</label><input id="w1" type="number" min={0} step="any" value={cfg.w1} onChange={(e) => setCfg({ ...cfg, w1: e.target.value })} /></div>
            <div><label htmlFor="w2">Round 2 weight</label><input id="w2" type="number" min={0} step="any" value={cfg.w2} onChange={(e) => setCfg({ ...cfg, w2: e.target.value })} /></div></div>
          <div className="md:col-span-2 flex items-center gap-3"><Button type="submit">Save configuration</Button><ErrorNote message={msg && msg !== "Saved." ? msg : null} />{msg === "Saved." && <span role="status" className="text-sm text-ok">Saved.</span>}</div>
        </form>
        <p className="mt-3 text-xs text-muted">No official weights are assumed: the combined leaderboard stays unavailable until both weights are set. Power-up tokens and the Big-O viva are not implemented and cannot be enabled.</p>
      </Card>
      <Card title="Submission monitor" action={<Button variant="ghost" onClick={() => void downloadCsv("/admin/export/submissions.csv?round=2", "submissions-round-2.csv")}>Export CSV</Button>}>
        <table className="w-full text-left text-sm"><thead className="text-xs text-muted uppercase"><tr><th className="py-2">Team</th><th>Final submissions</th><th>Last result</th></tr></thead>
          <tbody>{subs.data?.map((s, i) => <tr key={i} className="border-t border-line/60"><td className="py-2">#{s.team_number}</td><td>{s.finals}</td><td><StatusBadge status={s.provider === "mock" ? "MOCK" : s.outcome} /></td></tr>)}
            {subs.data?.length === 0 && <tr><td colSpan={3} className="py-3 text-muted">Round 2 has not started.</td></tr>}</tbody></table>
      </Card>
    </div>
  );
}
