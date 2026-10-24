import Link from "next/link";
import { PublicBoard } from "@/components/arena/PublicBoard";

export default function Leaderboard() {
  return (
    <main className="mx-auto w-full max-w-4xl flex-1 px-4 py-10">
      <Link href="/" className="mb-6 inline-block text-sm text-muted hover:text-fg">← The Optimization Arena</Link>
      <PublicBoard />
    </main>
  );
}
