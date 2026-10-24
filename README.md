# The Optimization Arena

Competition platform for a college code-optimization event (Round 1: Legacy Code Autopsy, Round 2: Live Optimization Duel).
Status: foundation + Round 1 set-up (teams, questions, variants, assignments, participant view). See `docs/DEVELOPMENT_LOG.md` for what is and is not implemented.

**Stack:** Next.js (App Router, TypeScript, Tailwind) · FastAPI + SQLAlchemy · Supabase (Postgres, Auth, RLS) · Gemini (planned).

## Setup
1. `cp .env.example .env` and fill in the values locally (never commit `.env`). `DATABASE_URL` must be the Supabase **Session pooler** string.
2. Python: `python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt`
3. Web: `cd web && npm install`
4. Database: migrations live in `supabase/migrations/` (already applied to the project).

## Run
```
# API (port 8010)
cd backend && ../.venv/bin/python -m uvicorn app.main:app --port 8010
# Web (port 3000; proxies /api/* to the API)
cd web && npm run dev
```

## Test
```
cd backend && ../.venv/bin/python -m pytest          # mocked + REAL Supabase tests (creates and deletes its own data)
cd web && npx tsc --noEmit && npm run lint && npm run build
cd web && npx playwright test                        # REAL end-to-end (starts API + web if not running)
```
