"use client";

import { useEffect, useState } from "react";
import { StatusBadge } from "@/components/arena/Badge";
import { Card } from "@/components/ui";
import { api } from "@/lib/api";

type Q = { title: string; category: string; variant_id: string };
type Sub = { id: string; kind: string; language: string; created_at: string; outcome: string | null; is_mock: boolean };

export default function Submissions() {
  const [rows, setRows] = useState<{ q: Q; subs: Sub[] }[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    (async () => {
      const { questions } = await api<{ questions: Q[] }>("/participant/questions");
      setRows(await Promise.all(questions.map(async (q) => ({ q, subs: (await api<{ submissions: Sub[] }>(`/participant/variants/${q.variant_id}/submissions`)).submissions }))));
    })().catch((e) => setErr(e.message));
  }, []);
  if (err) return <p role="alert" className="text-danger">{err}</p>;
  if (!rows) return <p className="text-muted">Loading…</p>;
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Submission history</h1>
      {rows.length === 0 && <p className="text-sm text-muted">Nothing to show yet.</p>}
      {rows.map(({ q, subs }) => (
        <Card key={q.variant_id} title={`${q.category} · ${q.title}`}>
          {subs.length === 0 ? <p className="text-sm text-muted">No runs or submissions yet.</p> : (
            <table className="w-full text-left text-sm"><thead className="text-xs text-muted uppercase"><tr><th className="py-1">Time (IST)</th><th>Type</th><th>Language</th><th>Result</th></tr></thead>
              <tbody>{subs.map((s) => (
                <tr key={s.id} className="border-t border-line/60"><td className="py-2">{new Date(s.created_at).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata" })}</td>
                  <td>{s.kind === "FINAL" ? "Final" : "Run"}</td><td className="font-mono text-xs">{s.language}</td>
                  <td><StatusBadge status={s.is_mock ? "MOCK" : s.outcome} /></td></tr>))}</tbody></table>
          )}
        </Card>
      ))}
    </div>
  );
}
