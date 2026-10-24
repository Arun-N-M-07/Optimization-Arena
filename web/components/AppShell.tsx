"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, type Me } from "@/lib/api";
import { createClient } from "@/lib/supabase/client";

const MeContext = createContext<Me | null>(null);
export const useMe = () => useContext(MeContext)!;

const NAV: Record<Me["role"], { href: string; label: string }[]> = {
  ADMIN: [
    { href: "/admin", label: "Overview" },
    { href: "/admin/teams", label: "Teams" },
    { href: "/admin/questions", label: "Questions" },
    { href: "/admin/assignments", label: "Assignments" },
    { href: "/admin/round-1", label: "Round 1" },
    { href: "/admin/finalists", label: "Finalists" },
    { href: "/admin/round-2", label: "Round 2" },
    { href: "/admin/judges", label: "Judges" },
    { href: "/admin/leaderboard", label: "Leaderboard" },
    { href: "/admin/announcements", label: "Announcements" },
    { href: "/admin/audit", label: "Audit" },
  ],
  PARTICIPANT: [
    { href: "/participant", label: "My team" },
    { href: "/participant/round-1", label: "Round 1" },
    { href: "/participant/round-2", label: "Round 2" },
    { href: "/participant/submissions", label: "Submissions" },
    { href: "/participant/results", label: "Results" },
  ],
  JUDGE: [{ href: "/judge", label: "Review queue" }],
};

/** Loads the caller from the backend (source of truth for role) and gates by role. */
export function AppShell({ role, children }: { role: Me["role"]; children: ReactNode }) {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Me>("/me")
      .then((m) => (m.role === role ? setMe(m) : router.replace(`/${m.role.toLowerCase()}`)))
      .catch((e) => (e.status === 401 ? router.replace("/login") : setError(e.message)));
  }, [role, router]);

  async function signOut() {
    await createClient().auth.signOut();
    router.replace("/login");
  }

  if (error) return <p className="p-8 text-danger" role="alert">{error}</p>;
  if (!me) return <p className="p-8 text-muted">Loading…</p>;

  return (
    <MeContext.Provider value={me}>
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
          <Link href="/" className="font-semibold tracking-tight">Optimization Arena</Link>
          <nav className="order-last flex w-full flex-wrap gap-x-4 gap-y-1 text-sm text-muted md:order-none md:w-auto md:flex-1">
            {NAV[me.role].map((n) => <Link key={n.href} href={n.href} className="hover:text-fg">{n.label}</Link>)}
          </nav>
          <span className="hidden text-xs text-muted sm:inline">{me.email} · {me.role}</span>
          <button onClick={signOut} className="ml-auto text-sm text-muted hover:text-fg md:ml-0">Sign out</button>
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8">{children}</main>
    </MeContext.Provider>
  );
}
