"use client";

import { Card } from "@/components/ui";
import { useLoad } from "@/lib/useLoad";

type Q = { category: string; question_id: string; title: string; difficulty: string; label: string; description: string;
  expected_behavior: string; constraints: string; languages: string[]; original_code: Record<string, string> };
type Resp = { round: { state: string; ends_at: string | null }; questions: Q[] };

export default function Round1() {
  const { data, error } = useLoad<Resp>("/participant/questions");
  if (error) return <p role="alert" className="text-danger">{error}</p>;
  if (!data) return <p className="text-muted">Loading…</p>;
  if (data.questions.length === 0)
    return <Card title="Round 1"><p className="text-sm text-muted">Round 1 has not started yet. Your questions will appear here when it does.</p></Card>;
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Round 1 · Legacy Code Autopsy</h1>
      {data.round.ends_at && <p className="text-sm text-muted">Ends {new Date(data.round.ends_at).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata" })} IST</p>}
      {data.questions.map((q) => (
        <Card key={q.question_id} title={`${q.category} · ${q.title}`} action={<span className="text-xs text-muted">{q.difficulty}</span>}>
          <p className="mb-3 whitespace-pre-wrap text-sm">{q.description}</p>
          <p className="mb-1 text-xs text-muted">Expected behaviour</p><p className="mb-3 whitespace-pre-wrap text-sm">{q.expected_behavior}</p>
          {q.constraints && <><p className="mb-1 text-xs text-muted">Constraints</p><p className="mb-3 whitespace-pre-wrap text-sm">{q.constraints}</p></>}
          <p className="mb-1 text-xs text-muted">Original implementation ({q.languages.join(", ")})</p>
          <pre className="overflow-x-auto rounded bg-surface2 p-3 font-mono text-xs">{q.original_code[q.languages[0]]}</pre>
          <p className="mt-3 text-xs text-muted">The code editor and submissions arrive in the next phase.</p>
        </Card>
      ))}
    </div>
  );
}
