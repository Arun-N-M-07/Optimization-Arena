# API (FastAPI, prefix `/api`; OpenAPI at `/docs` when running)

Auth: `Authorization: Bearer <Supabase access token>` unless noted. Errors: `{"detail": ...}`; 401 unauthenticated, 403 wrong role, 404 hidden/not yours, 409 state conflict (round closed, locked, duplicate), 422 validation, 429 run burst.

**Public** (no auth, published data only): `GET /public/state`, `GET /public/leaderboard?round=1|2|final`, `GET /health`.

**Any user**: `GET /me`.

**Participant** (`PARTICIPANT`): `GET /participant/team|questions|results`; per variant: `GET .../drafts`, `PUT .../draft`, `POST .../run`, `POST .../submit` (header `Idempotency-Key`), `GET .../submissions`, `GET|PUT .../report`, `POST .../report/submit` (the report is saved first; `report.evaluation_state` is `null`/`PENDING`/`DELAYED`/`COMPLETE`, also returned by `GET .../report`), `POST .../report/amend`.

**Judge/Admin review** (`JUDGE` scoped to assigned teams, `ADMIN` all): `GET /judge/queue`, `GET /judge/reports/{id}`, `POST /judge/reports/{id}/review`, `PUT /admin/teams/{id}/manual-scores`.

**Admin** (`ADMIN`): teams/members/accounts (`/admin/teams`, `/admin/users`), questions & variants (`/admin/questions`, `/admin/variants/{id}/status`), assignments (`/admin/assignments`, `PUT|DELETE /admin/teams/{id}/assignments/{category}`, `POST /admin/assignments/lock`), rounds (`GET /admin/rounds`, `PUT /admin/rounds/{n}/config`, `POST /admin/rounds/1/start`, `POST /admin/rounds/2/start`, `POST /admin/rounds/{n}/end|publish`), finalists (`/admin/finalists`, `/admin/finalists/lock`), judges (`/admin/judges`, `PUT /admin/judges/{id}/teams`), announcements, monitoring (`/admin/submissions`, `/admin/evaluations`, `POST /admin/reports/{id}/evaluate`, `POST /admin/evaluations/run-pending` — a bounded batch: ≤20 jobs, 4 in parallel, none started that could not finish within ~250 s; returns `processed`, `counts`, `waiting`, `complete`), `/admin/leaderboard`, `/admin/audit`, CSV `/admin/export/leaderboard.csv|submissions.csv`.
