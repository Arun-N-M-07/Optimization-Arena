# Known limitations (honest list)
**Blocked / external**
- **NOT DEPLOYED.** Two new Vercel projects (frontend, backend) are needed; exact steps in DEPLOYMENT.md. Every hosted behaviour (live URLs, Supavisor/transaction-pooler behaviour, function concurrency and latency, region placement, the client address the backend sees across the frontend-to-backend rewrite, Realtime over the public domain, CSP on the real domain) is **NOT VERIFIED**; the container image build is untested too.
- **Supabase Auth sign-in rate limit** (per IP) will lock out a large lab unless raised — see DEPLOYMENT.md §4b.
- **No real code execution (BLOCKED, see SANDBOX.md).** No isolated sandbox provider has been selected, configured or verified. The judge is `disabled` (default) or `mock`. Code correctness and performance are therefore not judged; code points are 0 by default and never awarded for mock/disabled results.
- **Not deployed.** The code is on GitHub (`main`) but no Vercel project exists for the backend or frontend.
- Hobby-plan suitability for an event is unconfirmed (non-commercial restriction).

**Not implemented**
- Pause state, scheduled state, power-up tokens, Big-O viva mechanics (kept off; cannot be enabled), constraint versioning during Round 2, SQL-evaluation databases (needs the sandbox), per-language original code editing in the admin form (one body is applied to all selected languages), password reset / self-service accounts, MFA, email notifications, judge-specific manual-score UI (API exists; admins have the UI).
- Combined leaderboard only when both weights are configured; no official formula is assumed. Default tie handling: tied totals share a rank (optional earliest-final-submission tie-break).

**Verification gaps**
- Not tested on a Vercel deployment; not load-tested beyond small concurrency tests.
- Genuinely expired JWTs were not generated (forged/garbage tokens are tested).
- Visual QA covers desktop and one mobile width for the screens inspected, not every screen at every width.
- Backend uses SQLAlchemy with SQL text, not ORM models.

**Operational notes**
- The last ≤1.5 s of typing can be lost if a tab is force-closed instantly; normal close/reload prompts the browser's "unsaved changes" guard.
- AI evaluation depends on Gemini availability; failures are visible to admins, retryable, and never block participants. On Vercel use `EVALUATION_MODE=inline` (a submission waits for Gemini, up to ~150 s worst case; a burst at the deadline can hit rate limits and leave reports *delayed* until an admin presses Run pending). A job needs a manual database reset after 6 failed attempts.
- Database/Auth network blips surface as retryable 503s; token validation calls Supabase on every request (no cache), which costs latency but keeps revocation immediate.
- The e2e Gemini step makes real API calls; model output varies, so tests assert validity and broad ranges only.
- Supabase Realtime is a hint; if it is down, pages refresh by polling every 10–15 s.
