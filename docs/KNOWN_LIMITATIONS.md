# Known limitations (honest list)
**Blocked / external**
- **No real code execution.** No isolated sandbox provider has been selected, configured or verified. The judge is `disabled` (default) or `mock`. Code correctness and performance are therefore not judged; code points are 0 by default and never awarded for mock/disabled results.
- **Not deployed.** Vercel project/Python function/rewrite are unconfigured; Vercel MCP was never connected. Nothing has been pushed to GitHub.
- Hobby-plan suitability for an event is unconfirmed (non-commercial restriction).

**Not implemented**
- Pause state, scheduled state, power-up tokens, Big-O viva mechanics (kept off; cannot be enabled), constraint versioning during Round 2, SQL-evaluation databases (needs the sandbox), per-language original code editing in the admin form (one body is applied to all selected languages), password reset / self-service accounts, MFA, email notifications, judge-specific manual-score UI (API exists; admins have the UI).
- Combined leaderboard only when both weights are configured; no official formula is assumed. Default tie handling: tied totals share a rank (optional earliest-final-submission tie-break).

**Verification gaps**
- Not tested on a Vercel deployment; not load-tested beyond small concurrency tests.
- Genuinely expired JWTs were not generated (forged/garbage tokens are tested).
- Visual QA covers desktop and one mobile width for the screens inspected, not every screen at every width.
- Backend uses SQLAlchemy with SQL text, not ORM models.
