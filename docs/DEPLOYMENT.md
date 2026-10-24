# Deployment preparation (nothing has been deployed)

## Findings (checked against Vercel docs, 2026)
- **Vercel Python runtime** supports FastAPI (zero-config, `app` entrypoint), Python 3.12/3.13/3.14, 500 MB bundle limit, Hobby function max duration 300 s.
- **Hobby plan is for non-commercial, personal use only.** Whether a college event qualifies is the organisers' call; use Pro if in doubt. Hobby also limits runtime logs to 1 hour.
- **Background work after the response is not guaranteed on serverless.** Set `EVALUATION_MODE=inline` (AI evaluation runs inside the submit request) or `manual` (admin presses *Run pending*). The default `background` is only for a long-lived server. Not yet tested on Vercel.
- **Realtime & the Next.js proxy** run on Vercel unchanged; `/api/*` must be routed to the FastAPI function (rewrite or Vercel Services). Not yet configured or tested.
- Session-pooler connections from serverless need `pool_size` kept small; the engine uses 5+5 and `prepare_threshold=None`.
- Google Cloud Run is not used.

## Pre-deployment checklist
1. Create/choose the Vercel team and project (never touch the unrelated `cybersecurity` project). Needs your authorization.
2. Env vars — **frontend**: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`, `API_ORIGIN`. **Backend only**: `SUPABASE_SECRET_KEY`, `DATABASE_URL` (Session pooler), `GEMINI_API_KEY`, `GEMINI_MODEL=gemini-3.5-flash-lite`, `JUDGE_PROVIDER=disabled`, `EVALUATION_MODE=inline`.
3. Migrations are already applied to the Supabase project; for a fresh project run `supabase/migrations/*` in order.
4. Create the first admin: create the user in Supabase Auth, then `update public.profiles set role = 'ADMIN' where email = '…'`.
5. Smoke tests: `/api/health`, login as each role, create a team, submit a draft.
6. Supabase: enable backups (paid plans) or export before the event; check Auth rate limits and site URL / redirect URLs.
7. Decide the sandbox provider before enabling real judging.

## Operations
- Health: `GET /api/health`. Logs: Vercel runtime logs + Supabase logs. Recovery: all state is in Postgres; participants' drafts survive refresh and redeploys.
