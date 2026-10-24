"use client";

import { Card } from "@/components/ui";
import { useLoad } from "@/lib/useLoad";

type Item = { title: string; category: string; label: string; total: number; comment: string | null;
  criteria: { criterion: string; marks: number; max_marks: number; explanation: string }[] };

export default function Results() {
  const { data, error } = useLoad<{ released: boolean; items: Item[] }>("/participant/results");
  if (error) return <p role="alert" className="text-danger">{error}</p>;
  if (!data) return <p className="text-muted">Loading…</p>;
  if (!data.released) return <Card title="Results"><p className="text-sm text-muted">Marks have not been released yet. They will appear here when the organisers publish Round 1 results.</p></Card>;
  const total = data.items.reduce((a, i) => a + i.total, 0);
  return (
    <div className="space-y-6">
      <div className="flex items-baseline justify-between"><h1 className="text-2xl font-semibold tracking-tight">Round 1 results</h1><span className="text-lg">Report marks: <b>{total}</b> / {data.items.length * 20}</span></div>
      {data.items.map((i) => (
        <Card key={i.title} title={`${i.category} · ${i.title}`} action={<span className="text-sm">{i.total} / 20</span>}>
          {i.criteria.length === 0 ? <p className="text-sm text-muted">No approved marks for this report.</p> : (
            <ul className="space-y-3 text-sm">{i.criteria.map((c) => (
              <li key={c.criterion}><div className="flex justify-between"><span className="font-medium">{c.criterion.charAt(0) + c.criterion.slice(1).toLowerCase()}</span><span>{c.marks} / {c.max_marks}</span></div>
                <p className="text-muted">{c.explanation}</p></li>))}</ul>
          )}
          {i.comment && <p className="mt-3 border-t border-line pt-3 text-sm"><span className="text-muted">Judge comment: </span>{i.comment}</p>}
        </Card>
      ))}
    </div>
  );
}
