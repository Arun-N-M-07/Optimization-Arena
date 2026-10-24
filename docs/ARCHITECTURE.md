# Architecture

```
Browser ──(Supabase Auth session cookie)──► Next.js (web/)
   │  Authorization: Bearer <Supabase access token>
   ▼
Next.js rewrites /api/* ──► FastAPI (backend/)  ──► Supabase Postgres (SQLAlchemy, Session Pooler)
   │                              └─► Supabase Auth admin API (create accounts)
   │                              └─► Gemini API (report evaluation only)
   └──(publishable key, RLS)──► Supabase Realtime (hints only)
```

- **One auth system.** Supabase Auth issues the session. FastAPI validates every bearer token with Supabase (so revoked/expired sessions are rejected), then loads `role` and `team_id` from `profiles`. The frontend never decides authorization; `/api/me` is the source of truth for the UI.
- **Backend owns the rules**: deadlines (Postgres `now()`), scoring, round state, authorization, audit.
- **Two DB access modes** (`backend/app/db.py`): `user_tx` runs `SET LOCAL ROLE authenticated` + the caller's JWT claims, so Postgres RLS applies to participant reads; `admin_tx` runs as the pooler's privileged role only after the backend authorized an ADMIN/JUDGE (or, for participant writes, after it verified team ownership and the round window). Both are single transactions; `SET LOCAL` cannot leak across pooled connections (tested).
- **Participant writes only via the API.** There are deliberately no INSERT/UPDATE policies for participants, so a participant cannot bypass deadline checks by calling PostgREST directly (tested).
- **Realtime is a hint.** Pages refetch authoritative state from the API on any event, on reconnect, on tab refocus, on `online`, and every 10–15 s. If Realtime is down everything still works.
- **Evaluation worker** (`python -m app.worker`): with `EVALUATION_MODE=worker` the API only stores a PENDING job; the worker claims jobs atomically and calls Gemini. Other modes: `background` (in-process after the response), `inline`, `manual`.
- **Judge abstraction** (`judge_provider.py`): `disabled` (default) | `mock` (dev/tests only, refused in production) | `judge0` (prepared, unverified; see SANDBOX.md). No code is executed anywhere in this system.
- **Gemini** (`gemini_eval.py`, `evaluation.py`): structured JSON validated by Pydantic; the backend recomputes totals; participant text is passed as JSON data, never in the system instruction.

## Round state machine
`DRAFT → RUNNING → ENDED → RESULTS_PUBLISHED` (publish/unpublish toggles `ENDED ↔ RESULTS_PUBLISHED`). `SCHEDULED` and `PAUSED` exist in the enum but are **not implemented** (no pause policy was defined). A `RUNNING` round whose `ends_at` has passed is reported as `ENDED` by every API call, even if nobody pressed "End".

## Round 2
Starting Round 2 creates one locked `DUEL` assignment per finalist for the same variant, so Round 2 reuses the same workspace, drafts, submissions, RLS and deadline code as Round 1.
