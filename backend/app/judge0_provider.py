"""Judge0 adapter (HTTP). PREPARED, NOT VERIFIED against a live Judge0 — keep JUDGE_PROVIDER=disabled until the
checklist in docs/SANDBOX.md has been completed against the real service you choose.

The sandbox is an external service: nothing here runs participant code. Each test case is an independent submission
(stdin + expected stdout); Judge0 does compilation, execution, CPU/memory/time limits and output limits.
"""
import base64
import json
import os
import time

import httpx

from .judge_provider import JudgeRequest, JudgeResult, MAX_MESSAGE_CHARS

# Judge0 CE v1.13 ids. They differ across Judge0 versions: verify with GET /languages and override via JUDGE0_LANGUAGE_IDS.
DEFAULT_IDS = {"c": 50, "cpp": 54, "java": 62, "python": 71}
# https://ce.judge0.com status ids -> our outcomes
STATUS = {3: "ACCEPTED", 4: "WRONG_ANSWER", 5: "TIME_LIMIT_EXCEEDED", 6: "COMPILATION_ERROR", 13: "SYSTEM_ERROR", 14: "SYSTEM_ERROR"}
RUNTIME_ERRORS = range(7, 13)    # SIGSEGV, SIGXFSZ, SIGFPE, SIGABRT, NZEC, other


class Judge0Provider:
    name = "judge0"

    def __init__(self, base_url: str | None = None, token: str | None = None, client: httpx.Client | None = None):
        self.base = (base_url or os.getenv("JUDGE0_URL", "")).rstrip("/")
        self.token = token or os.getenv("JUDGE0_TOKEN", "")
        self.ids = {**DEFAULT_IDS, **json.loads(os.getenv("JUDGE0_LANGUAGE_IDS", "{}"))}
        self.client = client or httpx.Client(timeout=httpx.Timeout(30.0, connect=5.0))

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.token:
            h["X-Auth-Token"] = self.token
        return h

    @staticmethod
    def _b64(s: str) -> str:
        return base64.b64encode(s.encode()).decode()

    def run(self, req: JudgeRequest) -> JudgeResult:
        if not self.base:
            return JudgeResult(outcome="SYSTEM_ERROR", total=len(req.tests), provider=self.name, message="Judge is not configured.")
        if req.language not in self.ids:
            return JudgeResult(outcome="SYSTEM_ERROR", total=len(req.tests), provider=self.name, message=f"Language {req.language} is not supported by this judge.")
        passed, worst, runtime, memory = 0, "ACCEPTED", 0, 0
        for t in req.tests:
            body = {"language_id": self.ids[req.language], "source_code": self._b64(req.code), "stdin": self._b64(t.input),
                    "expected_output": self._b64(t.expected_output), "cpu_time_limit": req.time_limit_ms / 1000,
                    "wall_time_limit": req.time_limit_ms / 1000 * 3, "memory_limit": req.memory_limit_kb,
                    "enable_network": False, "enable_per_process_and_thread_time_limit": True,
                    "enable_per_process_and_thread_memory_limit": True, "max_file_size": 1024}     # KB: caps output size
            try:
                r = self.client.post(f"{self.base}/submissions?base64_encoded=true&wait=true", json=body, headers=self._headers())
                r.raise_for_status()
                d = r.json()
            except (httpx.HTTPError, ValueError):
                return JudgeResult(outcome="SYSTEM_ERROR", total=len(req.tests), provider=self.name, message="The judge is temporarily unavailable. Your submission was saved.")
            sid = (d.get("status") or {}).get("id")
            runtime = max(runtime, int(float(d.get("time") or 0) * 1000))
            memory = max(memory, int(d.get("memory") or 0))
            if sid == 3:
                passed += 1
                continue
            outcome = STATUS.get(sid) or ("RUNTIME_ERROR" if sid in RUNTIME_ERRORS else "SYSTEM_ERROR")
            if sid == 5 and (d.get("memory") or 0) >= req.memory_limit_kb:
                outcome = "MEMORY_LIMIT_EXCEEDED"
            if worst == "ACCEPTED":
                worst = outcome
            if outcome == "COMPILATION_ERROR":
                msg = ""
                if d.get("compile_output"):
                    msg = base64.b64decode(d["compile_output"]).decode(errors="replace")[:MAX_MESSAGE_CHARS]
                return JudgeResult(outcome=outcome, passed=0, total=len(req.tests), provider=self.name, message=msg)
            if outcome == "SYSTEM_ERROR":     # provider-side failure: never reported as the team's wrong answer
                return JudgeResult(outcome=outcome, total=len(req.tests), provider=self.name, message="The judge reported an internal error. Your submission was saved.")
        return JudgeResult(outcome=worst, passed=passed, total=len(req.tests), runtime_ms=runtime, memory_kb=memory, provider=self.name,
                           message="" if worst == "ACCEPTED" else f"{passed}/{len(req.tests)} tests passed")
