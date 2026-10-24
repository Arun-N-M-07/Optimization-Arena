# Deployment

**Status: NOT DEPLOYED.** Everything below is prepared and checked locally (production-mode API start, production Next build, fail-fast config, worker). Creating the hosted projects needs *your* accounts; steps are exact. Container image build is **NOT TESTED** (no Docker daemon was available).

## Topology
```
Browser ──► Vercel (Next.js, web/) ──/api/* rewrite──► Railway "arena-api" (FastAPI)  ──► Supabase (Postgres via Session pooler, Auth, Realtime)
                                                       Railway "arena-worker" (python -m app.worker) ──► Supabase + Gemini
Browser ──────────────────────────────────────────────► Supabase Realtime / Auth (publishable key only)
```
Same-origin `/api` means no CORS (the API deliberately has none). Hosting facts checked in Vercel docs (Oct 2026): FastAPI supported, Hobby = **non-commercial personal use only**, function max 300 s. Vercel is used for the **frontend only**; the backend needs a long-lived process for the worker, so it runs on a container host (Railway chosen; Judge0 can *not* run there — see SANDBOX.md).

## 1. GitHub — DONE
`main` is pushed (commit `089131d` and ancestors; no force). The history was scanned for secrets before pushing. Keep pushing normally; never force-push.

## 2. Supabase (existing project — do not create another)
- Migrations 1–6 are already applied (`supabase/migrations/`). For any future change apply only new additive files.
- Auth → URL Configuration: **Site URL** = your Vercel production URL; **Redirect URLs** add `https://<vercel-domain>/auth/callback`.
- Create the first admin: create a user (Auth → Users), then SQL: `update public.profiles set role = 'ADMIN' where email = '<email>';`.
- Backups: enable Point-in-Time/daily backups if your plan has them; otherwise export before the event (Dashboard → Database → Backups).

## 3. Railway (backend) — two services from the same repo
**arena-api**: New project → Deploy from GitHub → Root Directory `backend` (uses `backend/railway.json`: Dockerfile, health check `/api/health`). Generate a public domain.
**arena-worker**: second service, same repo and root directory; *Settings → Config-as-code file* = `/backend/railway.worker.json` (start command `python -m app.worker`, no health check, no public domain).

Variables (both services; set in the dashboard, never in git):
| Variable | Value |
|---|---|
| `APP_ENV` | `production` (enables fail-fast config, hides /docs, HSTS) |
| `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | from Supabase → API |
| `SUPABASE_SECRET_KEY` | Supabase secret key (**backend only**) |
| `DATABASE_URL` | Supabase **Session pooler** URI (**backend only**) |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | key (**backend only**), `gemini-3.5-flash-lite` |
| `JUDGE_PROVIDER` | `disabled` until SANDBOX.md is completed (then `judge0`); `mock` is refused in production |
| `EVALUATION_MODE` | `worker` (API only stores the job; the worker evaluates) |
| `LOG_LEVEL` | `INFO` |
The API refuses to start in production if any required variable is missing or unsafe (logs say which).

## 4. Vercel (frontend) — NEW project, never the existing `cybersecurity` one
Import the repo → **Root Directory `web`** → framework Next.js (auto). Environment variables: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`, `API_ORIGIN=https://<arena-api railway domain>` (read at build time for the `/api` rewrite and CSP). Production branch `main`. Leave production deployment protection **off** for the production domain so participants and the projector can open it. Redeploy after changing any variable.

## 4b. Settings only you can change (found during testing — do these before the event)
- **Supabase Auth rate limit (critical):** sign-ins are limited **per IP address** (default ≈ 30 per 5 minutes). A load test hit `429` almost immediately. On competition day every participant will likely sign in from the same campus network, so **raise it** (Supabase Dashboard → Authentication → Rate Limits → *Rate limit for sign-ups and sign-ins*), or stagger logins, or have participants sign in *before* the event (sessions then persist). Unraised, a lab of 50+ students will be locked out for minutes.
- **Region:** every database round trip costs ~140 ms from a distant host (measured from the dev machine to the Seoul-region Supabase pooler). Put the Railway services in the **region closest to your Supabase project** (Supabase → Settings → Infrastructure shows it; this project's pooler is `ap-northeast-2`). Co-location is the single biggest latency lever.
- **Pooler capacity:** `DB_POOL_SIZE`+`DB_MAX_OVERFLOW` (default 6+2) for the API plus the worker (`DB_POOL_SIZE=2`, `DB_MAX_OVERFLOW=0`) must fit within the Session-pooler pool size (Supabase → Database → Settings → Connection pooling).

## 5. Post-deploy verification (do all before announcing the URL)
`curl https://<api>/api/health` → ok; `/api/ready` → `database: true`; `/docs` → 404; sign in as admin → System status panel shows no unexpected warnings and "Code judge: disabled (not real)"; create a **test** team/participant, submit a draft, submit a report, confirm the worker evaluates it (admin → Round 1 → Report evaluations), then delete the test data (Teams page; test names clearly prefixed `TEST`).

## Rollback
- **Frontend**: Vercel → Deployments → previous deployment → *Promote to Production*.
- **Backend**: Railway → service → Deployments → *Redeploy* a previous build. The schema is additive, so older API builds keep working against it.
- **Database**: never roll back by reset. Migrations are additive; if a migration was wrong, add a new corrective migration. Use backups only for data recovery.
- **Emergency stop of submissions**: Admin → Round N → **End round now** (server-side; takes effect immediately for every endpoint).
