# Competition-day runbook

## Before the event (T-1 day)
1. Deployment verified (DEPLOYMENT.md §5). `/api/ready` green; admin **System status** shows no unexpected warnings.
2. Supabase backup/export taken. Auth Site URL and redirect URLs point at the production domain.
3. Accounts created: every team (2–3 members), every participant login, judges (with their teams assigned). Test the logins from a phone and a lab PC.
4. Questions published; every active team has DSA + OOP + DBMS assigned; **Lock assignments** shows no blocking issues.
5. **Code execution**: decide honestly. If `Code judge` shows *not real*, participants' Run/Submit are saved but never judged — tell them, and rely on the Autopsy Report + manual review. Do not enable a provider that has not passed `scripts/sandbox_selftest.py`.
6. Remove all `TEST` data. Open `/projector` on the big screen and confirm it reads "Results have not been published yet".

## During Round 1 (9:30–12:00)
- Start: Assignments → **Start Round 1** (locks assignments; server timer starts, 150 min).
- Watch: Admin overview (System status, submissions, pending evaluations) and Round 1 → Submission monitor.
- AI evaluation: reports are queued the moment teams submit. If "failed" appears: Round 1 → Report evaluations → **Retry** (safe, never double-scores). Participants of a failed one see "evaluation delayed — nothing to resubmit". After a burst or an outage press **Run pending now** until it reports nothing waiting (each press does a bounded batch; jobs are persisted and never double-scored).
- Announcements: Announcements page; they appear live on every screen.
- **Stop everything now:** Round 1 → **End round now**. Effective immediately on the server for drafts, runs, submissions and reports.
- Browser trouble: drafts autosave every ~1.5 s and survive refresh; the editor falls back to a plain text box if Monaco cannot load.

## Between rounds
1. Judges open **Review queue**, check the Gemini assessment, adjust marks with a reason, **Approve**. Only approved reports count. Overrides appear in Audit.
2. Leaderboard (private view) → check totals → enter viva/bonus under Manual score if used.
3. Round 1 → **Publish results** (participants see marks; public board fills).
4. Finalists → select → Save → **Lock**. Round 2 → choose the common problem → Save → **Start Round 2** (60 min).

## Round 2 and results
End Round 2 → manual scores if used → **Publish results** → projector shows live. Combined ranking appears only if both weights were set — decide the formula with the organisers *before* the event; the system will not invent one.

## Incidents
| Symptom | Action |
|---|---|
| Users see "database temporarily unavailable" | Transient; clients retry. Check Supabase status and `/api/ready`. Nothing is lost (writes are transactional). |
| `/api/ready` 503 | DB unreachable: check Supabase and `DATABASE_URL` (Transaction pooler, port 6543). Liveness `/api/health` stays green by design. |
| Evaluations stuck | Admin overview warning → Round 1 → Report evaluations → Retry, or **Run pending now** (repeat until nothing is waiting). A job whose function was killed becomes claimable again after 5 minutes. |
| Gemini quota/outage | Reports are still saved; judges can review and approve manually without an AI assessment. |
| Wrong mark published | Judge/admin re-reviews (new approved review supersedes; history kept); unpublish → fix → republish. |
| Requests hang/time out on one report or team | A stuck session may hold a row lock; Postgres ends idle-in-transaction sessions after 60 s on its own. Check Supabase → Reports → Database for long transactions. |
| Must pause everyone | End round now (no pause state exists). |
| Rollback a bad deploy | DEPLOYMENT.md → Rollback. Never reset the database. |

## After the event
Export CSVs (Leaderboard, Round monitors), export the audit log, take a final Supabase backup, then rotate the Gemini key and Supabase secret key if they were ever shared.
