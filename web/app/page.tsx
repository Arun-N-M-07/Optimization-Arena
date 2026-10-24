import Link from "next/link";

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col justify-center gap-8 px-4 py-20">
      <div>
        <p className="mb-3 text-sm tracking-widest text-accent uppercase">College code optimization event</p>
        <h1 className="text-5xl font-semibold tracking-tight">The Optimization Arena</h1>
        <p className="mt-5 max-w-xl text-lg text-muted">
          Take working but inefficient code, make it faster without changing what it does, and defend your decisions.
        </p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="rounded-lg border border-line bg-surface p-5">
          <h2 className="font-semibold">Round 1 · Legacy Code Autopsy</h2>
          <p className="mt-2 text-sm text-muted">9:30 AM – 12:00 PM · 150 minutes. Optimize one DSA, one OOP and one DBMS problem, then write the autopsy report.</p>
        </div>
        <div className="rounded-lg border border-line bg-surface p-5">
          <h2 className="font-semibold">Round 2 · Live Optimization Duel</h2>
          <p className="mt-2 text-sm text-muted">1:30 PM – 2:30 PM · 60 minutes. Finalists solve one common problem under the clock.</p>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-4"><Link href="/login" className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-strong">Sign in</Link>
        <Link href="/leaderboard" className="text-sm text-muted hover:text-fg">Leaderboard</Link><Link href="/schedule" className="text-sm text-muted hover:text-fg">Schedule</Link><Link href="/rules" className="text-sm text-muted hover:text-fg">Rules</Link></div>
    </main>
  );
}
