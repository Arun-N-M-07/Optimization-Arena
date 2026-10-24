"use client";

import { useState } from "react";
import { Button, Card, ErrorNote } from "@/components/ui";
import { api } from "@/lib/api";
import { errText, useLoad } from "@/lib/useLoad";

export default function Announcements() {
  const { data, reload } = useLoad<{ announcements: { id: string; round: number | null; message: string; created_at: string }[] }>("/public/state");
  const [text, setText] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  async function act(fn: () => Promise<unknown>) { setMsg(null); try { await fn(); await reload(); } catch (e) { setMsg(errText(e)); } }
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Announcements</h1>
      <Card title="New announcement">
        <form className="flex gap-3" onSubmit={(e) => { e.preventDefault(); void act(async () => { await api("/admin/announcements", { method: "POST", body: JSON.stringify({ message: text }) }); setText(""); }); }}>
          <input aria-label="Announcement" required maxLength={500} placeholder="Shown live to every participant and on the projector" value={text} onChange={(e) => setText(e.target.value)} /><Button type="submit">Publish</Button></form>
        <div className="mt-2"><ErrorNote message={msg} /></div>
      </Card>
      <Card title="Recent">
        <ul className="space-y-2 text-sm">{data?.announcements.map((a) => (
          <li key={a.id} className="flex items-center justify-between gap-3"><span>{a.message} <span className="text-xs text-muted">· {new Date(a.created_at).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata" })}</span></span>
            <Button variant="danger" onClick={() => void act(() => api(`/admin/announcements/${a.id}`, { method: "DELETE" }))}>Delete</Button></li>))}
          {data?.announcements.length === 0 && <li className="text-muted">None yet.</li>}</ul>
      </Card>
    </div>
  );
}
