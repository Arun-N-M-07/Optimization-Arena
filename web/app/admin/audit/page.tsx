"use client";

import { useLoad } from "@/lib/useLoad";

type E = { created_at: string; action: string; entity: string; entity_id: string | null; details: Record<string, unknown>; actor: string | null };

export default function Audit() {
  const { data, error } = useLoad<E[]>("/admin/audit?limit=200");
  if (error) return <p role="alert" className="text-danger">{error}</p>;
  if (!data) return <p className="text-muted">Loading…</p>;
  return (
    <div className="space-y-4"><h1 className="text-2xl font-semibold tracking-tight">Audit log</h1>
      <div className="overflow-x-auto rounded-lg border border-line bg-surface"><table className="w-full text-left text-sm">
        <thead className="border-b border-line text-xs text-muted uppercase"><tr><th className="px-4 py-3">Time (IST)</th><th>Actor</th><th>Action</th><th>Entity</th><th>Details</th></tr></thead>
        <tbody>{data.map((e, i) => <tr key={i} className="border-b border-line/60 align-top last:border-0"><td className="px-4 py-2 whitespace-nowrap">{new Date(e.created_at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })}</td>
          <td>{e.actor ?? "—"}</td><td className="font-mono text-xs">{e.action}</td><td>{e.entity}</td><td className="max-w-md truncate font-mono text-xs text-muted" title={JSON.stringify(e.details)}>{JSON.stringify(e.details)}</td></tr>)}</tbody></table></div></div>
  );
}
