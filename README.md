# The Optimization Arena

Competition platform for a college code-optimization event: **Round 1 · Legacy Code Autopsy** (three assigned problems + a four-part Autopsy Report, AI-assisted and human-approved) and **Round 2 · Live Optimization Duel** (finalists, one common problem). Roles: participant, admin, judge, public projector.

**Stack:** Next.js (App Router, TypeScript, Tailwind, Monaco) · FastAPI + SQLAlchemy · Supabase (Postgres, Auth, Realtime, RLS) · Gemini (`gemini-3.5-flash-lite`, report evaluation only).

> **Important:** no real code execution exists. The judge is `disabled` (default) or a clearly labelled `mock`; see [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md). Nothing is deployed or pushed.

## Setup
1. `cp .env.example .env` and fill it in locally (never commit `.env`). `DATABASE_URL` must be the Supabase **Session pooler** URL (the direct host is IPv6-only).
2. `python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt`
3. `cd web && npm install --legacy-peer-deps`
4. Migrations in `supabase/migrations/` are already applied to the project; for a fresh project apply them in order.
5. First admin: create a user in Supabase Auth, then `update public.profiles set role = 'ADMIN' where email = '…'`.

## Run
```
cd backend && ../.venv/bin/python -m uvicorn app.main:app --port 8010      # API   (OpenAPI at /docs)
cd web && npm run dev                                                      # Web   http://localhost:3000 (proxies /api/* to 8010)
```
For local demos set `JUDGE_PROVIDER=mock` in `.env` to see labelled mock results. Port 8000 is not used here on purpose.

## Test
```
cd backend && ../.venv/bin/python -m pytest         # unit + REAL Supabase/Postgres/RLS/Gemini tests (~13 min; creates and deletes its own data)
cd web && npx vitest run                            # component/hook tests
cd web && npx tsc --noEmit && npm run lint && npm run build
cd web && npx playwright test                       # REAL browser journeys (starts API with the mock judge + web)
```
Docs: [architecture](docs/ARCHITECTURE.md) · [database](docs/DATABASE.md) · [API](docs/API.md) · [security](docs/SECURITY.md) · [testing](docs/TESTING.md) · [deployment](docs/DEPLOYMENT.md) · guides for [participants](docs/PARTICIPANT_GUIDE.md), [admins](docs/ADMIN_GUIDE.md), [judges](docs/JUDGE_GUIDE.md) · [limitations](docs/KNOWN_LIMITATIONS.md) · [log](docs/DEVELOPMENT_LOG.md).
