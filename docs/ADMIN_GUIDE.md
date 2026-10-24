# Admin guide
First admin: create a user in Supabase Auth and set `profiles.role = 'ADMIN'` (see DEPLOYMENT.md). Then everything is in the UI.
1. **Teams**: create a team (unique number), add 2–3 members, create each participant's login (admin sets the initial password).
2. **Questions**: create DSA/OOP/DBMS questions (and a DUEL question for Round 2), add variants (A, B, …) with languages, original code, visible tests, **hidden tests and reference solution (server-only)**, then publish the question and each variant (publishing needs original code per language and ≥ 1 hidden test).
3. **Judges**: create judge accounts and tick the teams each judge may see.
4. **Assignments**: one DSA, OOP and DBMS variant per team. *Lock assignments* checks every active team has ≥ 2 members and 3 assignments. **Start Round 1** locks them and starts the 150-minute server timer.
5. **Round 1**: monitor submissions and AI evaluations (retry failures, *Run pending*), export CSV. **End round now** (or let the timer end it). Judges approve marks; only approved reports count. **Publish results** makes them visible to participants and the public leaderboard.
6. **Finalists** (after Round 1 ended): select, save, lock. **Round 2**: pick the published DUEL variant, set duration (default 60), start. Real-judge points are 0 unless you configure them; the combined leaderboard stays off until you set **both** weights. Enter judged scores under **Leaderboard → Manual score**. End and publish.
7. **Announcements** appear live for participants and on the projector. **Audit** lists every administrative action. Open `/projector` on the big screen.
Power-up tokens and the Big-O viva are **not implemented**.
