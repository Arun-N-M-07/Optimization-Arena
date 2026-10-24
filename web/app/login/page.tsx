"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, type Me } from "@/lib/api";
import { createClient } from "@/lib/supabase/client";
import { Button, ErrorNote } from "@/components/ui";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const { error } = await createClient().auth.signInWithPassword({ email, password });
    if (error) {
      setError("Invalid email or password.");
      setBusy(false);
      return;
    }
    try {
      const me = await api<Me>("/me");
      router.replace(`/${me.role.toLowerCase()}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load your profile.");
      setBusy(false);
    }
  }

  return (
    <div className="m-auto w-full max-w-sm px-4 py-16">
      <h1 className="mb-1 text-2xl font-semibold tracking-tight">Sign in</h1>
      <p className="mb-6 text-sm text-muted">The Optimization Arena</p>
      <form onSubmit={onSubmit} className="space-y-4 rounded-lg border border-line bg-surface p-6">
        <div>
          <label htmlFor="email">Email</label>
          <input id="email" type="email" required autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div>
          <label htmlFor="password">Password</label>
          <input id="password" type="password" required autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </div>
        <ErrorNote message={error} />
        <Button type="submit" disabled={busy} className="w-full">{busy ? "Signing in…" : "Sign in"}</Button>
      </form>
    </div>
  );
}
