import Link from "next/link";

export default function Schedule() {
  return (
    <main className="mx-auto w-full max-w-3xl flex-1 px-4 py-12">
      <Link href="/" className="text-sm text-muted hover:text-fg">← Home</Link>
      <h1 className="mt-4 mb-6 text-3xl font-semibold tracking-tight">Schedule</h1>
      <table className="w-full text-left text-sm"><thead className="text-xs text-muted uppercase"><tr><th className="py-2">Time (IST)</th><th>Round</th><th>Duration</th></tr></thead>
        <tbody>
          <tr className="border-t border-line"><td className="py-3">9:30 AM – 12:00 PM</td><td>Round 1 · Legacy Code Autopsy</td><td>150 minutes</td></tr>
          <tr className="border-t border-line"><td className="py-3">1:30 PM – 2:30 PM</td><td>Round 2 · Live Optimization Duel (finalists)</td><td>60 minutes</td></tr>
        </tbody></table>
      <p className="mt-6 text-sm text-muted">Start and end times shown inside the app always come from the organisers&apos; server clock, not your device.</p>
    </main>
  );
}
