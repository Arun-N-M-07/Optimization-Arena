import Link from "next/link";

export default function Rules() {
  return (
    <main className="mx-auto w-full max-w-3xl flex-1 px-4 py-12">
      <Link href="/" className="text-sm text-muted hover:text-fg">← Home</Link>
      <h1 className="mt-4 mb-6 text-3xl font-semibold tracking-tight">How it works</h1>
      <div className="space-y-6 text-sm leading-6">
        <section><h2 className="mb-1 font-semibold">Teams</h2><p className="text-muted">Teams of 2–3 participants. Your team number stays the same in both rounds.</p></section>
        <section><h2 className="mb-1 font-semibold">Round 1 · Legacy Code Autopsy</h2>
          <p className="text-muted">Each team receives three working but inefficient programs: one Data Structures &amp; Algorithms, one Object-Oriented Programming and one Database (SQL) problem. Different teams may receive different variants of the same category. Optimize each without changing its behaviour, submit your solution, then write an Autopsy Report with four parts: inefficiency identification, optimization approach, complexity analysis, and trade-offs. Each part is worth 5 marks (20 per report).</p></section>
        <section><h2 className="mb-1 font-semibold">Round 2 · Live Optimization Duel</h2><p className="text-muted">Finalists from Round 1 solve one common problem in 60 minutes.</p></section>
        <section><h2 className="mb-1 font-semibold">Marking</h2><p className="text-muted">Reports are first assessed by an AI assistant, then every mark is reviewed and approved by a human judge, who can change it. The AI never decides final scores and never judges code correctness. Results are shown only when the organisers publish them.</p></section>
        <section><h2 className="mb-1 font-semibold">Fair play</h2><p className="text-muted">Work only within your team. Deadlines are enforced by the server. Attempts to access other teams&apos; work, hidden tests or the scoring system are blocked and logged.</p></section>
      </div>
    </main>
  );
}
