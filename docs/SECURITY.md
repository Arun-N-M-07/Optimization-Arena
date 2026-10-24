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

## Code execution
**Nothing executes participant code.** `JUDGE_PROVIDER=disabled` by default (honest "not enabled" result); `mock` returns fake results labelled MOCK and never counts for scores. A real provider needs an isolated sandbox (microVM or hardened container service with CPU/memory/time limits, no network, read-only FS, cleanup, no access to app secrets) — none has been selected or verified. See KNOWN_LIMITATIONS.

## Known gaps
- No rate limiting beyond the run-burst limit; no CAPTCHA/lockout on login (Supabase Auth has its own limits).
- No MFA. Admin-chosen initial passwords.
- Expired-token handling is tested with forged/garbage tokens; a genuinely expired JWT was not generated.
- Supabase advisor WARN for the four RLS helper functions is intentional (see DATABASE.md).
