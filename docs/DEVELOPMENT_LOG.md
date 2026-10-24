# Development Log

## Milestone 5 — Production readiness pass (2026-10-24)  — NOT DEPLOYED
**Verified results (final working tree)**
- Backend `pytest`: **127 passed** (real Supabase/Postgres/RLS/Gemini included). Vitest **34 passed**. `tsc`, `eslint`, `next build` clean.
- Playwright **12 passed** against the **production build** (`next build && next start`, real CSP/headers, real Gemini, Realtime).
- Production-mode API start verified locally against the real environment: fail-fast config, `/docs` 404, HSTS, `/api/ready` database true; refuses `JUDGE_PROVIDER=mock`. Worker started/stopped on SIGTERM. Lockfile installs and imports on a clean Python 3.13 venv.
- Built client bundle scanned for the Supabase secret key, Gemini key, DB URL and password: none. Full git history scanned (pattern + exact values): none.
- Supabase: remote migrations match local files 1–7; RLS on all tables; `anon` reads 2 tables, no browser role can write (migration 6); Realtime publication correct; advisors reviewed.

**Real defects found by testing/measurement and fixed**: orphaned `idle in transaction` session held a report-row lock 16+ min behind the pooler → per-connection `idle_in_transaction_session_timeout`/`lock_timeout` (+ migration 7, + tested on the real DB); public-cache invalidation raced with committing writers and with slow readers → clear after commit + generation counter (tested); per-request latency dominated by round trips → token cache, idle-only connection pings, single-statement role setup (autosave p50 1250→675 ms); unhandled upstream/DB errors → 503; error text could carry SQL parameters → hidden; unfiltered public endpoints → cached.

**Findings that need you (not fixable in code)**: Supabase Auth sign-in rate limit per IP will lock out a large lab (raise it); host the API in the Supabase region; sandbox provider decision (SANDBOX.md); Railway/Vercel/GitHub authorizations (DEPLOYMENT.md).

**Environment note**: one full run was invalidated by this machine's network dropping (DNS failures); data left behind was removed by name pattern and the suite rerun green.

**Not done / NOT TESTED**: real code execution (BLOCKED); hosted deploy, container image build (no Docker daemon), live URLs; load at event scale (24 concurrent synthetic participants max, local API → remote DB); DBMS/PostgreSQL judging.

## Milestone 4 — Workspace, judging abstraction, Gemini, review, Round 2, public views (2026-10-24)
**Recovered** from an interrupted session: the earlier `F` was a network interruption that left test data behind; removed only `ZZ …` teams / `arena-test-…` users, baseline then 27/27.

**Implemented**
- Migrations 4–5 (additive; an earlier draft containing `DROP` was declined by the tool, so judge scoping uses RESTRICTIVE policies instead).
- Backend: drafts/run/submit/history/report APIs (server-clock deadlines, idempotency, run rate-limit), judge provider abstraction (`disabled` default, labelled `mock`), Gemini evaluator (structured output, retry, injection handling) + job lifecycle, judge/admin review with audited overrides, backend scoring + ranking, finalists, Round 2 start/config/end/publish, announcements, manual scores, audit/CSV exports, public state/leaderboard, `EVALUATION_MODE`.
- Frontend: Monaco workspace (uncontrolled, fallback textarea), autosave with backoff + unsaved-changes guard, report editor, participant dashboard/results/history/Round 2, judge queue + review, admin Round 1/2, finalists, judges, leaderboard, announcements, audit, projector + public leaderboard, rules/schedule.
- Docs: README + ARCHITECTURE, DATABASE, API, SECURITY, TESTING, DEPLOYMENT, three guides, KNOWN_LIMITATIONS.

**Verified results (exact, final working tree)**
- Backend `pytest`: **89 passed** (≈9 min; real Supabase/Postgres/RLS/Gemini included).
- Vitest: **34 passed** (4 files). `tsc`, `eslint`, `next build`: clean.
- Playwright: **12 passed** on the real stack (two consecutive green runs after the last UI change).
- Real Gemini (`gemini-3.5-flash-lite`): 4 passed (valid structure, strong report ≥13/20, weak report ≤8, injection resisted) and exercised live in the judge E2E step.
- Supabase advisors: security — only intentional items; performance — see docs/DATABASE.md.
- DB left clean after every run (0 teams/questions/users; rounds DRAFT).

**Real bugs found by tests and fixed**: stale report load could overwrite typing and autosave empty (regression test added; verified it fails without the fix); Monaco dropped keystrokes under fast input; AI retry blocked 5 min; report submit deadlock + unserialized duplicate submit; Round 2 config rejected on unchanged resubmit; Supabase network timeout → bare 500 (now pooled client + retry + 503; DB drop → 503); admin buttons double-clickable mid-request; mock results shown as "Accepted".

**Blocked / not done**: no real code-execution sandbox (judge disabled/mock only); not deployed or pushed; Vercel MCP never connected; power-ups/viva/pause not implemented; SQL evaluation DBs need the sandbox; see docs/KNOWN_LIMITATIONS.md.

## Milestones 1–3 — see git history (foundation, Next.js + auth, teams/questions/assignments).
