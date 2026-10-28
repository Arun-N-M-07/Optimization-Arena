const TONES: Record<string, string> = {
  ACCEPTED: "border-ok/50 text-ok", EVALUATED: "border-ok/50 text-ok", REVIEWED: "border-ok/50 text-ok", PUBLISHED: "border-ok/50 text-ok",
  COMPLETED: "border-ok/50 text-ok", RUNNING: "border-accent/60 text-accent", SUBMITTED: "border-accent/60 text-accent",
  EVALUATION_PENDING: "border-amber-400/50 text-amber-300", EVALUATION_DELAYED: "border-danger/60 text-danger", PENDING: "border-amber-400/50 text-amber-300", DRAFT: "border-line text-muted",
  WRONG_ANSWER: "border-danger/60 text-danger", COMPILATION_ERROR: "border-danger/60 text-danger", RUNTIME_ERROR: "border-danger/60 text-danger",
  TIME_LIMIT_EXCEEDED: "border-danger/60 text-danger", MEMORY_LIMIT_EXCEEDED: "border-danger/60 text-danger",
  SYSTEM_ERROR: "border-amber-400/50 text-amber-300", FAILED: "border-danger/60 text-danger", ENDED: "border-line text-muted",
  RESULTS_PUBLISHED: "border-ok/50 text-ok", MOCK: "border-amber-400/60 text-amber-300",
};

export const LABELS: Record<string, string> = {
  EVALUATION_PENDING: "Evaluating", EVALUATION_DELAYED: "Evaluation delayed", SYSTEM_ERROR: "System error", WRONG_ANSWER: "Wrong answer", COMPILATION_ERROR: "Compilation error",
  RUNTIME_ERROR: "Runtime error", TIME_LIMIT_EXCEEDED: "Time limit exceeded", MEMORY_LIMIT_EXCEEDED: "Memory limit exceeded",
  RESULTS_PUBLISHED: "Results published", MOCK: "Mock — not executed",
};

export function StatusBadge({ status, className = "" }: { status: string | null | undefined; className?: string }) {
  if (!status) return null;
  const label = LABELS[status] ?? status.charAt(0) + status.slice(1).toLowerCase();
  return <span data-status={status} className={`inline-block rounded border px-2 py-0.5 text-xs font-medium ${TONES[status] ?? "border-line text-muted"} ${className}`}>{label}</span>;
}
