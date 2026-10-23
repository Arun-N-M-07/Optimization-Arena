# Development Log

## Milestone 1 — Foundation (2026-10-24)
**Done**
- Git: `main`, origin = Arun-N-M-07/Optimization-Arena, comprehensive `.gitignore`.
- Supabase (project ref in `.env` URL): migrations `20261024000001_core_schema`, `20261024000002_function_search_path` applied and mirrored in `supabase/migrations/`. 16 tables, RLS on all, `question_private` has no policies (server-only).
- Backend `backend/`: FastAPI app, settings, Supabase-token auth, role dependencies (`/api/health`, `/api/me`, `/api/admin/ping`).
- Tests: `cd backend && ../.venv/bin/python -m pytest` → 8 passed (auth/role enforcement, fake gateway).
- Live checks: secret key reads `profiles` (200); publishable key reads `teams` → `[]`, `question_private` → `[]`.

**Not done / blockers**
- `DATABASE_URL` (Postgres pooler string with DB password) is not set → SQLAlchemy layer, and anything needing transactions, is blocked. User must add it to local `.env`.
- Vercel + Supabase MCP show "pending approval" in the CLI listing, though the Supabase MCP tools did work in this session. Vercel tools are not loaded.
- No execution sandbox provider chosen → real code execution stays disabled.
- No Supabase Auth users or seed data yet; no frontend scaffold yet.

**Next**: Next.js scaffold + login, then teams/questions/assignments API and UI.
