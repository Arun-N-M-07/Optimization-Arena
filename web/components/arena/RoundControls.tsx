"use client";

import { useState } from "react";
import { StatusBadge } from "./Badge";
import { Button, Card, ErrorNote } from "@/components/ui";
import { api } from "@/lib/api";
import { errText } from "@/lib/useLoad";

export type RoundInfo = { round: number; state: string; starts_at: string | null; ends_at: string | null; results_published: boolean; finalists_locked: boolean; config: Record<string, unknown> };
const fmt = (s: string | null) => (s ? new Date(s).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", hour12: true }) + " IST" : "—");

export function RoundControls({ info, onChange, startAction }: { info: RoundInfo; onChange: () => void; startAction?: () => Promise<unknown> }) {
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function run(fn: () => Promise<unknown>, confirmText?: string) {
    if (confirmText && !window.confirm(confirmText)) return;
    setBusy(true); setMsg(null);
    try { await fn(); onChange(); } catch (e) { setMsg(errText(e)); } finally { setBusy(false); }
  }
  const n = info.round;
  return (
    <Card title={`Round ${n} control`} action={<StatusBadge status={info.state} />}>
      <dl className="mb-4 grid grid-cols-2 gap-2 text-sm"><dt className="text-muted">Started</dt><dd>{fmt(info.starts_at)}</dd><dt className="text-muted">Ends</dt><dd>{fmt(info.ends_at)}</dd>
        <dt className="text-muted">Results</dt><dd>{info.results_published ? "Published" : "Not published"}</dd></dl>
      <div className="flex flex-wrap gap-2">
        {["DRAFT", "SCHEDULED"].includes(info.state) && startAction && <Button disabled={busy} onClick={() => run(startAction, `Start Round ${n} now?`)}>Start Round {n}</Button>}
        {info.state === "RUNNING" && <Button variant="danger" disabled={busy} onClick={() => run(() => api(`/admin/rounds/${n}/end`, { method: "POST" }), `End Round ${n} now? Participants will no longer be able to submit.`)}>End round now</Button>}
        {["ENDED"].includes(info.state) && <Button disabled={busy} onClick={() => run(() => api(`/admin/rounds/${n}/publish`, { method: "POST", body: JSON.stringify({ published: true }) }), "Publish results? They become visible on the public leaderboard and to participants.")}>Publish results</Button>}
        {info.state === "RESULTS_PUBLISHED" && <Button variant="ghost" disabled={busy} onClick={() => run(() => api(`/admin/rounds/${n}/publish`, { method: "POST", body: JSON.stringify({ published: false }) }), "Unpublish results?")}>Unpublish</Button>}
      </div>
      <div className="mt-2"><ErrorNote message={msg} /></div>
    </Card>
  );
}
