# Development Log

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
