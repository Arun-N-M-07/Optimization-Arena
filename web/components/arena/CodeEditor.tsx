"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";

const Monaco = dynamic(() => import("@monaco-editor/react"), { ssr: false });
const MONACO_LANG: Record<string, string> = { c: "c", cpp: "cpp", java: "java", python: "python", sql: "sql" };

/**
 * Monaco editor, UNCONTROLLED after mount: Monaco owns the text while the user types (a controlled `value` races with
 * React state and can drop keystrokes on fast typing/paste). `value` is only the initial content; the parent remounts
 * the editor (change `key`) for deliberate external replacements such as a language switch or restoring starter code.
 * If Monaco cannot load (offline venue, blocked CDN) after `fallbackMs`, a plain textarea
 * takes over so a team can never be locked out of typing its solution.
 */
export function CodeEditor({ value, onChange, language, readOnly = false, fallbackMs = 12000, height = "420px" }:
  { value: string; onChange: (v: string) => void; language: string; readOnly?: boolean; fallbackMs?: number; height?: string }) {
  const [ready, setReady] = useState(false);
  const [fallback, setFallback] = useState(false);
  useEffect(() => {
    if (ready) return;
    const t = setTimeout(() => setFallback(true), fallbackMs);
    return () => clearTimeout(t);
  }, [ready, fallbackMs]);

  if (fallback && !ready)
    return (
      <div>
        <p className="mb-1 text-xs text-amber-300">The code editor could not load, so a plain text editor is shown. Your work is still saved.</p>
        <textarea aria-label="Code editor (plain)" spellCheck={false} readOnly={readOnly} value={value} onChange={(e) => onChange(e.target.value)}
          className="font-mono text-sm" style={{ height }} />
      </div>
    );
  return (
    <div className="overflow-hidden rounded-md border border-line" style={{ height }} data-testid="monaco-host">
      <Monaco height="100%" theme="vs-dark" language={MONACO_LANG[language] ?? "plaintext"} defaultValue={value}
        onChange={(v) => onChange(v ?? "")} onMount={() => setReady(true)}
        options={{ readOnly, minimap: { enabled: false }, fontSize: 14, scrollBeyondLastLine: false, automaticLayout: true, tabSize: 4, wordWrap: "on", ariaLabel: "Code editor" }} />
    </div>
  );
}
