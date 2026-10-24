# Database

Migrations (`supabase/migrations/`, applied in order to the Supabase project, never reset):

| # | File | Purpose |
|---|---|---|
| 1 | core_schema | 16 tables, enums, RLS, triggers (max 3 members, report immutability), signup → profile trigger |
| 2 | function_search_path | pin `search_path` on trigger functions |
| 3 | actor_fk_set_null | deleting an account keeps its history (`ON DELETE SET NULL`) |
| 4 | workspace_review_scoring | `code_drafts`, `judge_assignments`, `manual_scores`; submission immutability trigger; evaluation fields; **RESTRICTIVE** judge-scope policies; Realtime publication |

Key invariants enforced in the database: unique team numbers; ≤ 3 members; one variant per category per team; unique `(team, idempotency_key)` for submissions; submissions cannot be updated; submitted reports cannot be edited; at most one AI evaluation per report+version; marks ≤ 5 per criterion; manual scores within bounds; `ends_at > starts_at`.

## Privacy model
- `question_private` (hidden tests, reference solutions, evaluator notes): RLS on, **no policies** → unreachable with any browser key.
- Participants read only their own team's rows (`can_see_team`). AI evaluations, criteria, adjustments, manual scores and audit logs are staff-only.
- Judges are limited to teams in `judge_assignments` by restrictive policies layered on the original ones (nothing dropped).
- `can_see_team`, `current_team_id`, `current_app_role`, `is_staff` are `SECURITY DEFINER` and callable by `authenticated` (required by RLS; they only answer about the caller). The Supabase advisor reports this as a WARN by design.
