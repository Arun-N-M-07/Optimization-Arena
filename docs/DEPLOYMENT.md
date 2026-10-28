# Deployment

**Status: NOT DEPLOYED.** The code and configuration below are prepared and checked locally. **No Vercel project exists, nothing has been deployed, and nothing about live Vercel or Supavisor behaviour has been observed** — see [What has and has not been verified](#what-has-and-has-not-been-verified). Do not announce a URL until the [post-deploy smoke tests](#7-deployment-procedure-and-smoke-tests) pass.

## Topology
```
Browser ──► Vercel project "arena-web"  (Next.js, Root Directory web)
              │  /api/* rewrite (same origin: no CORS)
              ▼
            Vercel project "arena-api"  (FastAPI, Root Directory backend, Python 3.12, region icn1/Seoul)
              ├─► Supabase Postgres  via the TRANSACTION pooler (port 6543)
              ├─► Supabase Auth admin API (create accounts, validate sessions)
              └─► Gemini API  (inline, inside the submit request — no worker)
Browser ──► Supabase Realtime / Auth directly (publishable key only)
```
- **Two separate Vercel projects.** The backend is its own project; it is never part of, and never replaces, the frontend project. Neither is your existing `cybersecurity` project.
- **Supabase** provides PostgreSQL, Auth and Realtime. It is the existing project: do not create another.
- **`EVALUATION_MODE=inline`**: the report is saved, then Gemini is called in the same request. **There is no permanent Python worker** on Vercel (a function cannot host one). `python -m app.worker`, `Dockerfile` and `railway*.json` remain in the repository only for container hosts and are **not used** by this topology; do not deploy them.
- **Code execution is disabled** (`JUDGE_PROVIDER=disabled`) until a sandbox is verified — [details](#8-code-execution-is-disabled).

## Plan
A lookup of your Vercel account found no team, so it is probably a personal (Hobby) account — confirm the plan in the dashboard. Hobby is **non-commercial use only**, allows one function region (`icn1` is set), limits cron jobs to once a day (none are used) and caps a function at 300 s (`vercel.json` sets exactly 300). Decide whether Hobby is acceptable for the event before deploying; Pro raises the duration limit (800 s) but nothing here depends on it.

## What has and has not been verified
| Verified locally (this repository, Python 3.12, exact pinned dependencies) | NOT verified — needs a real deployment |
|---|---|
| Offline backend test suite; production-mode start-up, headers, fail-fast configuration (smoke tests) | Anything on a live Vercel deployment: cold starts, concurrency, real latency, the number of function instances |
| `vercel build` succeeds; function config is Python 3.12, `maxDuration` 300, `regions: ["icn1"]`; tests, scripts, `.env`, Dockerfile are excluded; pinned versions are what gets bundled | That `icn1` takes effect (project-level regions are applied when a deployment is created) |
| Inline evaluation, retries, bounded "Run pending" and participant status, against a throwaway local Postgres (also through a local PgBouncer in transaction mode) | **Supavisor** (Supabase's pooler). PgBouncer only models transaction pooling; behaviour differences are possible |
| Client-IP rules and rate limits (unit and middleware tests) | What client address the backend sees across the Vercel-to-Vercel rewrite — [§5](#5-client-ip-and-rate-limiting) |
| `vercel.json` validates against Vercel's published JSON schema | Gemini latency/quota under a real submission burst; Supabase Auth limits; Realtime on the public domain; CSP on the real domain |
| Dependency audit of the pinned set found no known vulnerabilities | The container image (`Dockerfile`) — no Docker daemon was available |

`tests/real` (which creates and deletes data in the live Supabase project) was deliberately **not** run for this work.

## 1. Supabase (existing project)
- Migrations 1–7 must be applied (`supabase/migrations/`). **Migration 7** sets `idle_in_transaction_session_timeout = 60s` and `lock_timeout = 15s` as role defaults; behind the transaction pooler these role defaults are what guarantee the timeouts, so confirm it is applied. For any future change apply only new additive files.
- Auth → URL Configuration: **Site URL** = the frontend's production URL; **Redirect URLs** add `https://<frontend-domain>/auth/callback`.
- First admin: create a user (Auth → Users), then SQL: `update public.profiles set role = 'ADMIN' where email = '<email>';`.
- Backups: enable Point-in-Time/daily backups if your plan has them; otherwise export before the event.
- Copy the **Transaction pooler** connection string (Dashboard → Connect; host `…pooler.supabase.com`, **port 6543**, user `postgres.<project-ref>`). It contains the database password: it goes only into the backend project's environment variables.

## 2. Backend project (`arena-api`) — new, separate
Create a **new** Vercel project from this repository. Settings:
- **Root Directory:** `backend`. Framework preset: FastAPI (should be auto-detected; entrypoint `app/main.py`, variable `app`). Build and install commands: leave default (dependencies come from `requirements.txt`, which is exactly pinned).
- Python **3.12** (`backend/.python-version`). Function **region `icn1`**, **max duration 300 s** (`backend/vercel.json`).
- **Deployment Protection:** the frontend's rewrite must reach the backend's production domain without a Vercel login. Check `curl https://<backend-domain>/api/health` returns `{"status":"ok"}` (not a Vercel sign-in page). Keep protection on for preview deployments.

### Backend environment variables (Production; mark secrets *Sensitive*; never commit them)
| Variable | Value | Secret? |
|---|---|---|
| `APP_ENV` | `production` (fail-fast config, hides `/docs`, HSTS) | no |
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase project URL | no |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | publishable key | no |
| `SUPABASE_SECRET_KEY` | secret key (`sb_secret_…`) — **backend only** | **yes** |
| `DATABASE_URL` | the **Transaction pooler** URL, port 6543 | **yes** |
| `GEMINI_API_KEY` | Gemini key — **backend only** | **yes** |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | no |
| `EVALUATION_MODE` | `inline` | no |
| `JUDGE_PROVIDER` | `disabled` (`mock` is refused in production) | no |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | `3` / `0` — [§3](#3-transaction-pooler-configuration) | no |
| `TRUSTED_PROXY_HOPS` | `1` — [§5](#5-client-ip-and-rate-limiting) | no |
| `LOG_LEVEL` | `INFO` | no |

Optional: `AUTH_CACHE_SECONDS` (default 30), `RATE_LIMIT_AUTHED_PER_MINUTE` / `RATE_LIMIT_ANON_PER_MINUTE` / `RATE_LIMIT_PUBLIC_PER_MINUTE` (600 / 600 / 6000), `RUN_PENDING_BUDGET_SECONDS` (250). **Do not set** `WORKER_*` or `JUDGE0_*`. The API refuses to start in production if a required value is missing or unsafe (the runtime log says which, never the value).

## 3. Transaction pooler configuration
**Use port 6543.** Session mode (5432) pins one Postgres connection per open client connection; the local test showed three simulated function instances (6 connections) cannot be served by 4 server connections in session mode, while 12 instances (36 connections) were served without error in transaction mode. The direct host is IPv6-only and is not used.

**Why the code is safe in transaction mode** (verified against a local PgBouncer in transaction mode with prepared-statement support turned **off**, with a deliberately tiny server pool; a negative control proved that setup does break named prepared statements):
- the driver never creates server-side prepared statements (`prepare_threshold=None`);
- row-level-security identity is set with `set_config(..., true)` inside one transaction, so it cannot leak to another client (960 mixed participant/admin transactions: zero leaks);
- a transaction stays on one server connection (so `SELECT … FOR UPDATE` and the claim `UPDATE` work);
- the safety timeouts come from migration 7's role defaults; the connect-time `SET` in `db.py` repeats the same values and is harmless;
- a connection dropped by the pooler is detected after 10 s idle, or surfaces as a retryable `503` + `Retry-After` straight after use.

**Rules for future code:** no session-level `SET`, `LISTEN/NOTIFY`, advisory locks held across transactions, temporary tables, or `WITH HOLD` cursors. (In the local test a session-level `SET` made by one client was visible to the next client.)

**Pool size: `DB_POOL_SIZE=3`, `DB_MAX_OVERFLOW=0`.** In the local model one pooled connection served about 44 requests/s (two 8 ms transactions each), so 3 connections ≈ 130 requests/s per function instance, far more than the event needs even if one instance took all traffic. Overflow 0 gives a hard ceiling: **client connections to the pooler = instances × 3**. Check Supabase → Database → Settings → Connection pooling for the pooler's pool size and maximum client connections and keep that product within it. If `database_ms` in the admin System status climbs under load, raise `DB_POOL_SIZE` to 4–5. These numbers come from a local model without network latency or TLS; treat them as a starting point, not a measurement of Supavisor.

## 4. Evaluation (`EVALUATION_MODE=inline`)
1. A participant submits a report. The report and a `PENDING` evaluation job are **committed first**.
2. In the same request Gemini is called (the database connection is not held meanwhile). Worst case for one evaluation is 151 s (3 attempts × 45 s timeout + back-off), inside the 300 s limit.
3. The result is stored, or on failure the job is marked `FAILED` — **the report is never lost, no marks are written, and the response is still HTTP 200** ("saved").
4. The participant is shown the truth, not just "submitted": **pending** (queued or running), **delayed** (the last attempt failed; organisers retry; nothing to resubmit) or **complete**. No marks, errors or attempt counts are shown to participants.
5. **Admin retry** (Round 1 → Report evaluations → Retry) re-runs one job inside the request. **Run pending now** evaluates a bounded batch: at most 20 jobs, 4 in parallel, and a job is started only if a worst-case run (151 s) still fits inside a 250 s budget. Jobs it did not start are untouched; the page says how many are still waiting — press again. A job another press or function already owns is skipped, never duplicated.
6. Claiming is an atomic database update with a unique index per report, so retries, parallel workers and simultaneous admins can never create a second evaluation or second set of marks. A function killed mid-evaluation leaves the job claimable again after 5 minutes. After 6 failed attempts a job needs a manual reset (known limitation).

Operational risks to plan for: a burst of submissions at the deadline can hit Gemini rate limits → some reports show *delayed*; afterwards use **Run pending now** until it says nothing is waiting. Each in-flight submission occupies one function for its duration.

## 5. Client IP and rate limiting
Rate limits are per **function instance** (in-process), keyed by:
- authenticated calls: a hash of the bearer token (the address is irrelevant);
- `/api/public/*` (read-only, served from a 3 s cache): the client address, separate larger budget (6000/min);
- other anonymous calls: the client address, 600/min.

**Trusted client-IP strategy.** `X-Forwarded-For` is a list each proxy appends to, so everything on its **left** is client-controlled. The app therefore:
- by default (`TRUSTED_PROXY_HOPS=0`) ignores every forwarding header and uses the TCP peer;
- with `TRUSTED_PROXY_HOPS=N` uses only the entry the N-th trusted proxy **from the right** appended; a header shorter than N entries, or an entry that is not an IP address, falls back to the peer; IPv6 is keyed by /64; the left-hand part is never read.

On Vercel set `TRUSTED_PROXY_HOPS=1`: Vercel's documentation says its edge **overwrites** `X-Forwarded-For` and does not forward client-supplied addresses. The container image no longer lets uvicorn trust the header from any source (`--no-proxy-headers`); on a container host behind proxies, set the hop count to the number of proxies you operate and no more.

**Unknown until deployed:** the frontend reaches the backend through a Vercel-to-Vercel rewrite. Vercel documents that a rewrite to an external origin forwards the visitor's address, but also that a deployment behind another proxy has `X-Forwarded-For` overwritten and external addresses not forwarded. Which of these applies to a Vercel-to-Vercel rewrite is not documented clearly, so the backend may see *every visitor as the frontend's egress address*. The design is correct either way — the only effect would be that all visitors share one anonymous budget, which is why `/api/public/*` has its own large one (100 viewers polling twice every 10 s is ≈ 1200/min against 6000). To check after deploying: from a network A send more than 600 unauthenticated requests/minute to `https://<frontend>/api/me` (each returns 401 until limited); at the same time request it once from network B (e.g. a phone on mobile data). B getting `429` means addresses are shared — acceptable, and you can leave the settings as they are. Add a Vercel Firewall rate-limit rule as an extra layer if you want one (not configured or verified here).

Residual risk (existing, not changed): requests with random invalid bearer tokens each get their own budget and each costs the backend one call to Supabase Auth. Supabase's own limits and a Vercel Firewall rule are the mitigations.

## 6. Frontend project (`arena-web`) — new, separate
New project, **Root Directory `web`**, framework Next.js (auto). Environment variables: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`, and `API_ORIGIN=https://<arena-api production domain>` (read at **build** time for the `/api` rewrite — redeploy after changing it). Production branch `main`. Leave protection off for the production domain so participants and the projector can open it. Deploy the **backend first** so its domain exists.

## 7. Deployment procedure and smoke tests
**Before creating anything (local):**
1. `cd backend && uv venv --python 3.12 .venv312 && uv pip install --python .venv312/bin/python -r requirements-dev.txt && .venv312/bin/python -m pytest tests --ignore=tests/real -q` — the offline suite on Python 3.12 (the database-backed suites skip themselves; any Python 3.12 virtualenv works instead of `uv`).
2. Optional isolated database suites: `scripts/local_pg_harness.sh start <dir>` (needs Postgres 16 and PgBouncer installed locally; loopback only) then `ARENA_LOCAL_DB=1 … pytest tests -q --ignore=tests/real`.
3. `cd web && npx tsc --noEmit && npx eslint . && npx vitest run`.
4. A secret scan of the diff (patterns for `sb_secret_`, JWTs, `postgres://user:password@`, API keys) and confirm `.env` is untracked.

**Deploy:** (1) create `arena-api`, set the environment variables above, deploy `main`; (2) run the backend smoke tests; (3) create `arena-web` with `API_ORIGIN`, deploy; (4) set Supabase Auth URLs; (5) run the frontend smoke tests.

**Backend smoke tests** (`B` = backend domain):
- `curl -s https://B/api/health` → `{"status":"ok"}`; `curl -s https://B/api/ready` → `"database": true`, `"evaluation_mode": "inline"`, `"environment": "production"`;
- `curl -s -o /dev/null -w '%{http_code}' https://B/docs` → `404`; `…/api/me` → `401`; `…/api/public/state` → `200`;
- response headers include `strict-transport-security`, `x-content-type-options`, `x-frame-options`; no `access-control-allow-origin`;
- Runtime Logs show "production configuration validated" and no errors.

**Frontend smoke tests** (`F` = frontend domain):
- `curl -s https://F/api/health` (goes through the rewrite) → ok; sign in as admin; the System status panel shows **Code judge: disabled (not real)**, no unexpected warnings, `database_ms` reasonable;
- create a **TEST** team and participant; sign in as it; save a draft, submit code, submit a report → the page shows *Evaluating*, then *evaluated* within seconds to a minute; Round 1 → Report evaluations shows `COMPLETED`; **Run pending now** says nothing is waiting;
- check a public leaderboard/projector page loads and a second browser sees an announcement live (Realtime);
- run the rate-limit check in §5; then delete all TEST data.

## 8. Code execution is disabled
`JUDGE_PROVIDER=disabled`: Run/Submit are saved but **never judged**, code points are never awarded, and the admin panel says so. `mock` is refused in production. The Judge0 adapter is written but has never run against a live Judge0 and needs a disposable VM you control — see [SANDBOX.md](SANDBOX.md), which also records that Vercel's own sandbox product has not been evaluated. **Do not run a real programming competition on this deployment until a provider passes `scripts/sandbox_selftest.py`.**

## 9. Settings only you can change
- **Supabase Auth rate limit (critical):** sign-ins are limited per IP (default ≈ 30 per 5 minutes). On competition day many participants share one campus address — raise it (Authentication → Rate Limits), or have participants sign in before the event.
- **Region:** the backend is set to `icn1` (Seoul) to sit next to this project's pooler (`ap-northeast-2`). Confirm the Supabase region in Settings → Infrastructure if it ever changes.
- **Pooler capacity:** keep (instances × `DB_POOL_SIZE`) within the pooler's maximum client connections ([§3](#3-transaction-pooler-configuration)).

## Rollback
- **Frontend / backend:** Vercel → Deployments → pick the previous deployment → *Promote to Production* (or Instant Rollback). The schema is additive, so older backend builds keep working against it.
- **Database:** never roll back by reset. Add a new corrective migration; use backups only for data recovery.
- **Emergency stop of submissions:** Admin → Round N → **End round now** (server-side, immediate for every endpoint).
