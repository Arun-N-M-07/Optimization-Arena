# Development Log

## Milestone 3 — Teams → Questions → Variants → Assignments (2026-10-24) — VERIFIED
**Implemented**
- Backend (`backend/app/`): `db.py` (SQLAlchemy engine, `admin_tx`, `user_tx`), routers `teams`, `questions`, `assignments`, `participant`.
- `user_tx` runs `SET LOCAL ROLE authenticated` + `request.jwt.claims`, so participant reads are filtered by the real RLS policies. Admin operations use `admin_tx` (postgres role) only after the backend has authorized an ADMIN.
- Rules enforced: unique team numbers (DB), max 3 members (DB trigger), min 2 members before assignments can be locked / Round 1 started (backend), one variant per category per team (DB unique), only published questions/variants assignable, category must match, assignments editable only while Round 1 is DRAFT/SCHEDULED, starting Round 1 locks them (after validation), membership frozen once locked, hidden tests / reference solutions live only in `question_private` (no RLS policies) and are never selected by participant queries. Participants see questions only after Round 1 starts.
- Every admin mutation writes `audit_logs` (assignment changes record the previous variant).
- Migration 3: audit/created-by FKs to `auth.users` are `ON DELETE SET NULL` so history survives account deletion.
- Frontend (`web/`): login, callback, session-refreshing `proxy.ts`, role-aware shell (role comes from backend `/api/me`), admin Overview / Teams / Questions / Assignments, participant Team / Round 1 (read-only questions).

**Tests executed (real results)**
- Backend `pytest`: **27 passed** (8 mocked-gateway auth; 4 real-Supabase auth; 15 real-Postgres+RLS slice tests).
- Real RLS checks in Postgres as a participant: sees only own team/members/assignments/variants; `question_private`, `audit_logs` and other profiles return 0 rows; writes blocked; teamless user sees nothing; role/claims do not leak between pooled transactions. Publishable key against PostgREST also returns `[]` for private tables.
- Playwright (real Next.js + FastAPI + Supabase): **3 passed** — signed-out redirects, wrong password, and the full admin→participant journey (team + members + login, 3 questions with variants published, incomplete-lock refused, assign, start round, participant sees own team and 3 questions, hidden/reference strings absent from the page, participant token gets 403 on admin APIs, session survives reload).
- `tsc`, `eslint`, `next build`: clean.
- All tests clean up after themselves; verified the DB returns to 0 teams/questions/users and Round 1 = DRAFT.

**Bugs found and fixed during verification**
- Tailwind not compiling (overwrote scaffold config) → PostCSS plugin.
- Unlabelled form inputs (a11y) → labels wrap inputs.
- Admin could click "Start Round 1" while an assignment request was in flight → controls disable while busy.
- `loadEnvConfig` in `next.config.ts` was a no-op under `next dev` (Next had already cached env) → `forceReload`, and public vars inlined via `env` so `proxy.ts` sees them.

**Known gaps / blockers**
- No Vitest/React Testing Library unit tests yet (browser tests cover auth + protected routes).
- Code editor, submissions, Autopsy Report, Gemini evaluation, judge adapter, scoring, leaderboard, Round 2, projector, realtime: **not implemented**.
- Code-execution provider not chosen → real execution stays disabled.
- Vercel MCP not connected/approved; nothing deployed; hosting plan/Python runtime suitability not yet verified.
- Backend uses SQLAlchemy Core with SQL text, not ORM models (deliberate for speed; revisit if models are needed).
- Participant accounts are created by an admin with an admin-chosen password (no self-service reset yet).
- Port 8000 on the dev machine was occupied by an unrelated process, so this project's API runs on **8010**.

## Milestone 2 — Next.js foundation + real auth (verified, see git history)
## Milestone 1 — Supabase schema, RLS, FastAPI auth (verified, see git history)
