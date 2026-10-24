"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { Button, Card, ErrorNote } from "@/components/ui";
import { errText, useLoad } from "@/lib/useLoad";

type Variant = { id: string; label: string; status: string; languages: string[]; hidden_tests: unknown[] };
type Question = { id: string; category: string; title: string; difficulty: string; status: string; variants: Variant[] };

const LANGS: Record<string, string[]> = { DSA: ["c", "cpp", "java", "python"], OOP: ["cpp", "java", "python"], DBMS: ["sql"], DUEL: ["c", "cpp", "java", "python"] };

export default function QuestionsPage() {
  const { data, error, reload } = useLoad<Question[]>("/admin/questions");
  const [msg, setMsg] = useState<string | null>(null);
  const [q, setQ] = useState({ category: "DSA", title: "", difficulty: "EASY" });

  async function run(fn: () => Promise<unknown>) {
    setMsg(null);
    try { await fn(); await reload(); } catch (e) { setMsg(errText(e)); }
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Questions</h1>
      <Card title="New question">
        <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); run(async () => { await api("/admin/questions", { method: "POST", body: JSON.stringify(q) }); setQ({ ...q, title: "" }); }); }}>
          <div className="w-32"><label htmlFor="qc">Category</label><select id="qc" value={q.category} onChange={(e) => setQ({ ...q, category: e.target.value })}><option>DSA</option><option>OOP</option><option>DBMS</option><option value="DUEL">DUEL (Round 2)</option></select></div>
          <div className="min-w-56 flex-1"><label htmlFor="qt">Title</label><input id="qt" required value={q.title} onChange={(e) => setQ({ ...q, title: e.target.value })} /></div>
          <div className="w-32"><label htmlFor="qd">Difficulty</label><select id="qd" value={q.difficulty} onChange={(e) => setQ({ ...q, difficulty: e.target.value })}><option>EASY</option><option>MEDIUM</option></select></div>
          <Button type="submit">Create question</Button>
        </form>
      </Card>
      <ErrorNote message={msg ?? error} />
      {data?.length === 0 && <p className="text-sm text-muted">No questions yet.</p>}
      <div className="space-y-4">{data?.map((x) => <QuestionCard key={x.id} q={x} run={run} />)}</div>
    </div>
  );
}

function QuestionCard({ q, run }: { q: Question; run: (fn: () => Promise<unknown>) => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const langs = LANGS[q.category];
  const blank = { label: "", description: "", expected_behavior: "", constraints: "", languages: [langs[0]], code: "", vin: "", vout: "", hin: "", hout: "", ref: "", concepts: "", complexity: "" };
  const [f, setF] = useState(blank);
  const set = (k: keyof typeof blank) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setF({ ...f, [k]: e.target.value });

  function submit(e: React.FormEvent) {
    e.preventDefault();
    run(async () => {
      // One code body is applied to every selected language here; per-language editing comes with the editor phase.
      const body = {
        label: f.label, description: f.description, expected_behavior: f.expected_behavior, constraints: f.constraints,
        languages: f.languages,
        original_code: Object.fromEntries(f.languages.map((l) => [l, f.code])),
        visible_tests: f.vin ? [{ input: f.vin, expected_output: f.vout }] : [],
        hidden_tests: f.hin ? [{ input: f.hin, expected_output: f.hout }] : [],
        reference_solution: Object.fromEntries(f.languages.map((l) => [l, f.ref])),
        reference_concepts: f.concepts, expected_complexity: f.complexity,
      };
      await api(`/admin/questions/${q.id}/variants`, { method: "POST", body: JSON.stringify(body) });
      setF(blank); setOpen(false);
    });
  }
  const status = (path: string, s: string) => run(() => api(path, { method: "PATCH", body: JSON.stringify({ status: s }) }));

  return (
    <Card title={`${q.category} · ${q.title}`}
      action={<div className="flex items-center gap-2 text-xs"><span className="text-muted">{q.difficulty} · {q.status}</span>
        {q.status !== "PUBLISHED" ? <Button onClick={() => status(`/admin/questions/${q.id}/status`, "PUBLISHED")}>Publish</Button>
          : <Button variant="ghost" onClick={() => status(`/admin/questions/${q.id}/status`, "DRAFT")}>Unpublish</Button>}</div>}>
      <ul className="mb-3 space-y-2 text-sm">
        {q.variants.map((v) => (
          <li key={v.id} className="flex items-center justify-between rounded border border-line px-3 py-2">
            <span>Variant <b>{v.label}</b> <span className="text-muted">· {v.languages.join(", ")} · {v.hidden_tests.length} hidden test(s)</span></span>
            <span className="flex items-center gap-2"><span className="text-xs text-muted">{v.status}</span>
              {v.status !== "PUBLISHED" ? <Button onClick={() => status(`/admin/variants/${v.id}/status`, "PUBLISHED")}>Publish</Button>
                : <Button variant="ghost" onClick={() => status(`/admin/variants/${v.id}/status`, "DRAFT")}>Unpublish</Button>}</span>
          </li>
        ))}
        {q.variants.length === 0 && <li className="text-muted">No variants yet.</li>}
      </ul>
      <button className="text-xs text-accent" onClick={() => setOpen(!open)}>{open ? "Cancel" : "Add variant"}</button>
      {open && (
        <form onSubmit={submit} className="mt-3 grid gap-3 md:grid-cols-2">
          <label>Label (e.g. A)<input required value={f.label} onChange={set("label")} /></label>
          <div><span className="mb-1 block text-xs text-muted">Languages</span>
            <div className="flex flex-wrap gap-3 pt-1 text-sm">{langs.map((l) => (
              <label key={l} className="flex items-center gap-1 text-fg"><input type="checkbox" className="w-auto" checked={f.languages.includes(l)}
                onChange={(e) => setF({ ...f, languages: e.target.checked ? [...f.languages, l] : f.languages.filter((x) => x !== l) })} />{l}</label>))}</div></div>
          <label className="md:col-span-2">Problem description<textarea rows={3} required value={f.description} onChange={set("description")} /></label>
          <label>Expected behaviour<textarea rows={2} required value={f.expected_behavior} onChange={set("expected_behavior")} /></label>
          <label>Constraints<textarea rows={2} value={f.constraints} onChange={set("constraints")} /></label>
          <label className="md:col-span-2">Original (inefficient) code<textarea rows={6} className="font-mono text-sm" required value={f.code} onChange={set("code")} /></label>
          <label>Visible test input<input value={f.vin} onChange={set("vin")} /></label>
          <label>Visible test expected output<input value={f.vout} onChange={set("vout")} /></label>
          <label>Hidden test input (server only)<input value={f.hin} onChange={set("hin")} /></label>
          <label>Hidden test expected output (server only)<input value={f.hout} onChange={set("hout")} /></label>
          <label className="md:col-span-2">Reference solution (server only)<textarea rows={4} className="font-mono text-sm" value={f.ref} onChange={set("ref")} /></label>
          <label>Reference concepts<input value={f.concepts} onChange={set("concepts")} /></label>
          <label>Expected complexity<input value={f.complexity} onChange={set("complexity")} /></label>
          <div className="md:col-span-2"><Button type="submit" disabled={f.languages.length === 0}>Create variant</Button></div>
        </form>
      )}
    </Card>
  );
}
