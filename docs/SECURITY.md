# Security

## Verified (by automated tests against the real project unless noted)
- Backend authorization per role; 401 for missing/invalid/forged tokens, 403 for wrong role (participant→admin/judge, judge→admin, admin→participant).
- Cross-team isolation in the API (404, not 403) and in Postgres RLS (participant, judge).
- Hidden tests and reference solutions never appear in participant/public responses or pages (API and browser tests), and `question_private` returns 0 rows to every browser role.
- Participants cannot write through PostgREST (no INSERT/UPDATE policies) so deadlines cannot be bypassed.
- Deadlines use the server clock; late draft/run/submit/report requests get 409.
- Submissions and submitted reports are immutable at the database level; duplicate requests are idempotent (concurrency tested with parallel requests).
- Gemini: strict schema, 0–5 caps, backend-computed totals, prompt-injection handling (unit tests with an injected model + real model checks).
- Every override/approval/round action is audit-logged; manual overrides keep previous marks and reason.
- Secrets: `.env` is git-ignored; only `NEXT_PUBLIC_SUPABASE_URL` / `..._PUBLISHABLE_KEY` reach the browser. Secret key, DB URL and Gemini key are read only by the backend (`config.py`). Staged files are scanned before every commit.

## Production hardening (added in the release pass)
- **Config fails closed:** with `APP_ENV=production` the API refuses to start if secrets are missing, `DATABASE_URL` is not the Session pooler, `JUDGE_PROVIDER=mock`, or `EVALUATION_MODE` is invalid (tested). `/docs` and `/openapi.json` are disabled; HSTS is sent.
- **Database privileges:** migration 6 removed all INSERT/UPDATE/DELETE/TRUNCATE rights from `anon` and `authenticated` on every table and all `anon` reads except the two public tables, so RLS is no longer the only barrier (tested: hard 401/403 on any write or private read via the REST API).
- **Request controls:** 1.5 MB body cap (including chunked), per-caller rate limit (600/min by token hash or address) with `Retry-After`, security headers on every response, no CORS (same-origin proxy), request ids, access log without headers/queries/bodies, SQL parameters hidden from error text, sanitized 500s (tested: secrets and participant code never reach the client).
- **Frontend:** CSP (script/style/connect allow-lists: self, jsDelivr for Monaco, the Supabase host), `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`, HSTS in production. The built client bundle was scanned for the Supabase secret key, Gemini key, DB URL and DB password: none present.
- **Identity cache trade-off:** validated tokens are trusted for `AUTH_CACHE_SECONDS` (default 30). A demoted/revoked user keeps access up to that long; set `0` to validate every request at the cost of ~480 ms per request at today's distance.
- **Orphaned transactions:** a dropped connection once left a session holding a report-row lock for 16+ minutes behind the pooler. Every API connection now sets `idle_in_transaction_session_timeout=60s` and `lock_timeout=15s` (tested on the real database, including that Postgres terminates an abandoned session and frees its lock).
- **Evaluation jobs** are rows in Postgres processed by a separate worker; claims are atomic, stale claims recover after 5 minutes, attempts are capped.
- **Real judge verdicts only:** code points require `execution_results.provider = 'judge0'`; no endpoint accepts a result from a client.

## Code execution
**Nothing executes participant code.** `JUDGE_PROVIDER=disabled` by default (honest "not enabled" result); `mock` returns fake results labelled MOCK and never counts for scores. A real provider needs an isolated sandbox (microVM or hardened container service with CPU/memory/time limits, no network, read-only FS, cleanup, no access to app secrets) — none has been selected or verified. See KNOWN_LIMITATIONS.

## Known gaps
- Rate limiting is in-process (one API instance); no CAPTCHA/lockout on login (Supabase Auth has its own limits). The CSP needs `'unsafe-inline'` for Next.js bootstrap scripts (no nonces).
- Monaco loads from jsDelivr (third-party CDN); the editor degrades to a textarea if unavailable. Self-hosting the assets would remove the dependency.
- No MFA. Admin-chosen initial passwords.
- Expired-token handling is tested with forged/garbage tokens; a genuinely expired JWT was not generated.
- Supabase advisor WARN for the four RLS helper functions is intentional (see DATABASE.md).
