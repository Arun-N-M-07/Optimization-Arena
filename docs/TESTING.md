# Testing

| Layer | Command | What it covers | Real services? |
|---|---|---|---|
| Backend unit | `cd backend && ../.venv/bin/python -m pytest tests/test_*.py` | auth/role enforcement (fake gateway), upstream/DB outage → 503, Gemini schema/retry/injection (injected model), ranking/ties, judge-provider safety | No (mocked) |
| Backend real | `cd backend && ../.venv/bin/python -m pytest tests/real` | real Supabase Auth tokens, real Postgres via SQLAlchemy, RLS as participant/judge, PostgREST abuse attempts, deadlines, idempotency/concurrency, immutability, AI job retry, judge override audit, scoring, finalists, Round 2, publication, exports; **real Gemini** (`test_real_gemini.py`) | **Yes** — creates throwaway users/teams/questions and deletes them; resets both rounds |
| Frontend unit | `cd web && npx vitest run` | autosave (debounce, flush, backoff, no overlap, unsaved-changes guard), report form validation/immutability, result panel (mock labelling), countdown on server clock, editor fallback, workspace (draft restore, per-language drafts, idempotency key, closed round, stale-load regression) | No (api mocked) |
| Types/lint/build | `cd web && npx tsc --noEmit && npm run lint && npm run build` | strict TypeScript, ESLint (React Compiler rules), production build | No |
| Browser E2E | `cd web && npx playwright test` | one serial story on **real Next.js + FastAPI + Supabase (Auth, Postgres, Realtime) + Gemini**: admin set-up → participant Monaco workspace (draft/restore/mock run/submit) → Autopsy Report (validate/persist/submit/immutable) → judge review of a real Gemini assessment with override → end/publish → public leaderboard → finalists → Round 2 → projector (live, read-only) → API security with real tokens | **Yes**; judge is the MOCK provider |

**Mocked vs real:** `tests/test_*.py` and Vitest use fakes. Everything under `tests/real/` and Playwright talks to the real Supabase project. Real tests take ~10–13 minutes because the database is remote.

**Important constraints**
- Real suites share one database and the two global round rows; run them one at a time (never backend real tests and Playwright concurrently).
- Playwright starts the API with `JUDGE_PROVIDER=mock`; no code is ever executed. The Gemini step needs `GEMINI_API_KEY` and takes ~15–60 s.

## Latest recorded results (this working tree)
See `docs/DEVELOPMENT_LOG.md` for the dated, exact results of each suite.

## Bugs found by testing (and fixed)
Report autosave could save an empty form over typed text after a late load; Monaco dropped keystrokes under fast typing (controlled value); AI retry was blocked for 5 min after a failure; concurrent report submit could deadlock; Round 2 settings were rejected when resubmitted unchanged; Run could return a bare 500 on a transient Supabase network timeout; Finalists/Assignments buttons could be clicked mid-request; mock results were shown with a green "Accepted" badge.
