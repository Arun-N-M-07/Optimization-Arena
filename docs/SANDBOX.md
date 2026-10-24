# Code-execution sandbox: decision record

**Status: BLOCKED.** No real sandbox is configured or verified. The judge is `disabled` (default) or `mock`; neither produces a correctness verdict. **Do not run a real programming competition on this build until a provider passes `scripts/sandbox_selftest.py`.**

## Options evaluated (sources are vendor/community pages, not audits — verify before paying)
| Option | Fit | Findings |
|---|---|---|
| **Judge0 CE, self-hosted on a Linux VM** | Best fit: C, C++, Java, Python out of the box; purpose-built for judging (CPU/wall/memory/output limits, stdin/expected-output, network off) | Needs a **privileged** container and cgroup access ([Judge0 on Railway: not supported](https://station.railway.com/questions/judge0-deployment-failing-with-cgroup-an-c536e4d6), [privileged permissions inquiry](https://station.railway.com/questions/inquiry-regarding-privileged-container-p-b1cb3a6e)); modern distros may need cgroup fixes ([EC2 guide](https://tutorialsdojo.com/self-hosting-judge0-a-step-by-step-guide-using-amazon-ec2-lambda-and-s3/)). So it must run on a **small VPS you control**, not on Railway. MIT-licensed, no per-run fees. Its isolation is Linux namespaces/cgroups on a shared kernel: strong for judging, still not a microVM — keep the VM disposable and network-isolated from everything else. |
| **Judge0 hosted (RapidAPI)** | Easy | Free/low tiers are capped at 50–5,000 submissions/day and 1,000 requests/hour ([judge0.com/ce](https://judge0.com/ce)); this adapter makes one request per test case, so a 40-team event would exhaust small plans. Shared third-party infrastructure on competition day. Not recommended unless a paid, dedicated plan is confirmed. |
| **E2B (Firecracker microVMs)** / **Modal sandboxes (gVisor)** | Stronger isolation | Per-second pricing; Modal denies inbound traffic by default ([comparison](https://northflank.com/blog/e2b-vs-modal), [benchmarks](https://www.superagent.sh/blog/ai-code-sandbox-benchmark-2026)). But they are general sandboxes, **not judges**: we would have to write and adversarially test our own compile/run/limit/compare runner for four languages. Viable, more work, needs your account. |
| Docker on the API host | **Rejected** | Shared kernel on the app server that holds secrets; explicitly forbidden. |

## Recommendation
Self-host **Judge0 CE on a dedicated, disposable Linux VM** (no access to Supabase credentials, outbound network blocked except what Judge0 needs), reachable only from the API with `JUDGE0_TOKEN`. The adapter (`backend/app/judge0_provider.py`) is written and unit-tested against a fake transport; it has **never been run against a live Judge0**.

## What you need to do (cannot be done for you)
1. Create the VM (any provider), install Docker, deploy Judge0 CE per its docs with `AUTHN_TOKEN` set; open port 2358 to the API host only.
2. Set on the API service: `JUDGE_PROVIDER=judge0`, `JUDGE0_URL`, `JUDGE0_TOKEN`; confirm language ids with `GET /languages` and override `JUDGE0_LANGUAGE_IDS` if they differ from the defaults (c=50, cpp=54, java=62, python=71).
3. Run `cd backend && ../.venv/bin/python -m scripts.sandbox_selftest` (infinite loop, memory exhaustion, output flood, fork bomb, network and secret/file access attempts, 12 concurrent jobs). Enable for participants only if it prints `ALL CHECKS PASSED`.

## Not covered
- **DBMS (SQL) questions:** Judge0 runs SQLite, not PostgreSQL. A faithful DBMS round needs a disposable, privilege-less Postgres per run — **NOT IMPLEMENTED**. Until then DBMS code is saved and judged by humans via the report.
- Mock results can never earn points: code points are only awarded when `execution_results.provider = 'judge0'` (tested), and results can only be written by the backend after calling the provider.
