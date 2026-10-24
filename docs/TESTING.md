# Testing

| Layer | Command | What it covers | Real services? |
|---|---|---|---|
| Backend unit | `cd backend && ../.venv/bin/python -m pytest tests/test_*.py` | auth/role enforcement (fake gateway), upstream/DB outage → 503, Gemini schema/retry/injection (injected model), ranking/ties, judge-provider safety | No (mocked) |
| Backend real | `cd backend && ../.venv/bin/python -m pytest tests/real` | real Supabase Auth tokens, real Postgres via SQLAlchemy, RLS as participant/judge, PostgREST abuse attempts, deadlines, idempotency/concurrency, immutability, AI job retry, judge override audit, scoring, finalists, Round 2, publication, exports; **real Gemini** (`test_real_gemini.py`) | **Yes** — creates throwaway users/teams/questions and deletes them; resets both rounds |
| Frontend unit | `cd web && npx vitest run` | autosave (debounce, flush, backoff, no overlap, unsaved-changes guard), report form validation/immutability, result panel (mock labelling), countdown on server clock, editor fallback, workspace (draft restore, per-language drafts, idempotency key, closed round, stale-load regression) | No (api mocked) |
| Types/lint/build | `cd web && npx tsc --noEmit && npm run lint && npm run build` | strict TypeScript, ESLint (React Compiler rules), production build | No |
| Browser E2E | `cd web && npx playwright test` | one serial story on **real Next.js + FastAPI + Supabase (Auth, Postgres, Realtime) + Gemini**: admin set-up → participant Monaco workspace (draft/restore/mock run/submit) → Autopsy Report (validate/persist/submit/immutable) → judge review of a real Gemini assessment with override → end/publish → public leaderboard → finalists → Round 2 → projector (live, read-only) → API security with real tokens | **Yes**; judge is the MOCK provider |

**Mocked vs real:** `tests/test_*.py` and Vitest use fakes. Everything under `tests/real/` and Playwright talks to the real Supabase project. Real tests take ~7–10 minutes because the database is remote.

**Important constraints**
- Real suites share one database and the two global round rows; run them one at a time (never backend real tests and Playwright concurrently).
- Playwright starts the API with `JUDGE_PROVIDER=mock`; no code is ever executed. The Gemini step needs `GEMINI_API_KEY` and takes ~15–60 s.

## Production-readiness additions
- `tests/test_production.py` (unit): security headers, body-size and chunked-body limits, rate limiting, sanitized 500s, fail-fast production config, `/docs` disabled in production, Judge0 adapter via a fake transport (status mapping, clipping, provider failures never become WRONG_ANSWER), CSV formula neutralisation, worker loop, token-cache semantics, idle-only connection verification.
- `tests/real/test_real_z2b_worker.py`: worker-mode persistence, exactly-once completion, crash recovery of stale claims, retry/exhaustion — on the real database.
- `tests/real/test_real_z2_review.py::test_least_privilege_*`: `anon` reads two tables only; no browser role can write anywhere.
- Playwright now runs against **`next build && next start`** (real CSP and production bundle), not the dev server.
- `scripts/loadtest.py`: concurrent synthetic participants against a real API process + real Supabase. `scripts/sandbox_selftest.py`: hostile-program checks for a real judge provider (**never run: no provider exists**).

### Measured performance (local API → Supabase Seoul pooler; round trip ≈ 140 ms; NOT a hosted staging environment)
24 concurrent synthetic participants for 60 s (autosave every 1.5 s, polling, runs; 0 errors, 0 × 5xx, `/api/ready` healthy after):

| Endpoint | before round-trip work (p50 / p95) | after (p50 / p95) |
|---|---|---|
| PUT draft (autosave) | 1250 / 2119 ms | **675 / 1756 ms** |
| GET questions (poll) | 1740 / 2904 ms | **955 / 1403 ms** |
| POST run | 2038 / 2408 ms | **1385 / 1740 ms** |

Round trips were reduced by caching validated tokens for 30 s, verifying pooled connections only after idling, and setting role+claims in one statement. Latency is now dominated by network distance to the database; a co-located host should be several times faster, but **that is not measured**. Capacity for the real event size is **NOT TESTED** (no staging host, 24 participants max, and Supabase Auth's sign-in limit blocks larger synthetic runs from one IP).

## Latest recorded results (this working tree)
Backend 127 passed · Vitest 34 passed · Playwright 12 passed (production build) · tsc/eslint/build clean. Dated details in `docs/DEVELOPMENT_LOG.md`.

## Bugs found by testing (and fixed)
Report autosave could save an empty form over typed text after a late load; Monaco dropped keystrokes under fast typing (controlled value); AI retry was blocked for 5 min after a failure; concurrent report submit could deadlock; Round 2 settings were rejected when resubmitted unchanged; Run could return a bare 500 on a transient Supabase network timeout; Finalists/Assignments buttons could be clicked mid-request; mock results were shown with a green "Accepted" badge.
