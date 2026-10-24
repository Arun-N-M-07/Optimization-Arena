import type { LiveState } from "@/lib/useRealtime";

export function LiveDot({ state }: { state: LiveState }) {
  const map = { live: ["bg-ok", "Live"], connecting: ["bg-muted", "Connecting"], reconnecting: ["bg-amber-400", "Reconnecting — refreshing every 15s"] } as const;
  const [c, t] = map[state];
  return <span className="inline-flex items-center gap-1.5 text-xs text-muted" role="status"><span className={`h-2 w-2 rounded-full ${c}`} />{t}</span>;
}
