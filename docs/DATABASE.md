# Database

Migrations (`supabase/migrations/`, applied in order to the Supabase project, never reset):

| # | File | Purpose |
|---|---|---|
| 1 | core_schema | 16 tables, enums, RLS, triggers (max 3 members, report immutability), signup → profile trigger |
| 2 | function_search_path | pin `search_path` on trigger functions |
| 3 | actor_fk_set_null | deleting an account keeps its history (`ON DELETE SET NULL`) |
| 4 | workspace_review_scoring | `code_drafts`, `judge_assignments`, `manual_scores`; submission immutability trigger; evaluation fields; **RESTRICTIVE** judge-scope policies; Realtime publication |
| 5 | hot_path_indexes | additive covering indexes for FK lookups on submissions/reports/drafts/adjustments |
| 6 | least_privilege_grants | revoke all write privileges from `anon`/`authenticated` on every table; `anon` may only read the two public tables |
| 7 | session_timeouts | role-level `idle_in_transaction_session_timeout=60s`, `lock_timeout=15s` (belt-and-braces; the API also sets them on every connection because the pooler reuses sessions) |

Key invariants enforced in the database: unique team numbers; ≤ 3 members; one variant per category per team; unique `(team, idempotency_key)` for submissions; submissions cannot be updated; submitted reports cannot be edited; at most one AI evaluation per report+version; marks ≤ 5 per criterion; manual scores within bounds; `ends_at > starts_at`.

## Privacy model
- `question_private` (hidden tests, reference solutions, evaluator notes): RLS on, **no policies** → unreachable with any browser key.
- Participants read only their own team's rows (`can_see_team`). AI evaluations, criteria, adjustments, manual scores and audit logs are staff-only.
- Judges are limited to teams in `judge_assignments` by restrictive policies layered on the original ones (nothing dropped).
- `can_see_team`, `current_team_id`, `current_app_role`, `is_staff` are `SECURITY DEFINER` and callable by `authenticated` (required by RLS; they only answer about the caller). The Supabase advisor reports this as a WARN by design.


## Advisor status
Security: only the intentional `question_private` (no policies) and the four RLS helper functions. Performance: two `auth_rls_initplan` warnings (`profiles_self`, `judge_assignments_self`) are left as-is — fixing them means rewriting existing policies, which was deliberately not done; impact is negligible at event scale. Remaining unindexed-FK infos are on cold audit/actor columns.
