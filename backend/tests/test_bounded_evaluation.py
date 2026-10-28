"""Admin 'Run pending' must never outlive its request: bounded batch, deadline-aware starts, parallel but claim-safe. No database needed."""
import collections
import inspect
import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import evaluation, gemini_eval
from app.auth import CurrentUser, current_user
from app.main import app

WORST = gemini_eval.WORST_CASE_SECONDS


class Fake:
    """Fake clock + fake jobs. Each job 'takes' `seconds` of fake time."""

    def __init__(self, monkeypatch, n, seconds=0.0, fail=()):
        self.now, self.calls, self.fail, self.seconds = 0.0, [], set(fail), seconds
        self.ids = [f"job-{i}" for i in range(n)]
        self.lock = threading.Lock()
        monkeypatch.setattr(evaluation, "_clock", lambda: self.now)
        monkeypatch.setattr(evaluation, "_eligible_ids", lambda limit: self.ids[:limit])
        monkeypatch.setattr(evaluation, "run_job", lambda jid: self.run_job(jid)[0])
        monkeypatch.setattr(evaluation, "_run_job", self.run_job)

    def run_job(self, jid):
        with self.lock:
            self.calls.append((jid, self.now))
            self.now += self.seconds
        if jid in self.fail:
            raise RuntimeError("db blip")
        return "COMPLETED", True


@pytest.mark.parametrize("seconds,expected", [(0, 20), (10, 10), (60, 2), (99, 2), (WORST, 1)])
def test_a_job_is_started_only_if_a_worst_case_run_still_fits_the_budget(monkeypatch, seconds, expected):
    f = Fake(monkeypatch, 20, seconds)
    out = evaluation.run_pending(limit=20, budget_seconds=250, workers=1)
    assert len(out) == expected == len(f.calls)
    assert all(start + WORST <= 250 for _, start in f.calls)           # every started job could finish inside the budget
    assert f.now <= 250 or seconds == 0                                  # ...and (with jobs no slower than worst case) the call did


def test_jobs_that_were_not_started_are_never_touched(monkeypatch):
    f = Fake(monkeypatch, 8, seconds=60)
    out = evaluation.run_pending(limit=20, budget_seconds=250, workers=1)
    started = {j for j, _ in f.calls}
    assert set(out) == started and started == {"job-0", "job-1"} and len(f.calls) == 2      # run_job (the only claimer) never saw job-2..7


def test_limit_caps_a_single_press(monkeypatch):
    Fake(monkeypatch, 50)
    assert len(evaluation.run_pending(limit=20, budget_seconds=250, workers=4)) == 20


def test_parallel_workers_run_each_job_exactly_once_and_never_more_than_the_worker_count(monkeypatch):
    ids, seen, live, peak, lock = [f"j{i}" for i in range(24)], collections.Counter(), [0], [0], threading.Lock()

    def run_job(jid):
        with lock:
            seen[jid] += 1
            live[0] += 1
            peak[0] = max(peak[0], live[0])
        time.sleep(0.01)
        with lock:
            live[0] -= 1
        return "COMPLETED", True
    monkeypatch.setattr(evaluation, "_eligible_ids", lambda limit: ids[:limit])
    monkeypatch.setattr(evaluation, "_run_job", run_job)
    out = evaluation.run_pending(limit=24, budget_seconds=250, workers=4)
    assert set(out) == set(ids) and set(seen.values()) == {1} and 1 < peak[0] <= 4


def test_one_failing_job_does_not_abandon_the_rest_when_bounded(monkeypatch):
    Fake(monkeypatch, 5, fail={"job-1"})
    out = evaluation.run_pending(limit=20, budget_seconds=250, workers=2)
    assert out["job-1"] == "ERROR" and [v for k, v in out.items() if k != "job-1"] == ["COMPLETED"] * 4


def test_without_a_budget_behaviour_is_unchanged_sequential_and_errors_propagate(monkeypatch):
    f = Fake(monkeypatch, 3)
    assert evaluation.run_pending(limit=10) == {"job-0": "COMPLETED", "job-1": "COMPLETED", "job-2": "COMPLETED"}
    f.fail.add("job-1")
    with pytest.raises(RuntimeError):
        evaluation.run_pending(limit=10)                              # the long-lived worker relies on this to back off


def test_endpoint_reports_what_is_still_waiting(monkeypatch):
    seen = {}
    monkeypatch.setattr(evaluation, "count_eligible", lambda: 30)
    monkeypatch.setattr(evaluation, "run_pending", lambda **kw: seen.update(kw) or {"a": "COMPLETED", "b": "FAILED", "c": "COMPLETED"})
    monkeypatch.delenv("RUN_PENDING_BUDGET_SECONDS", raising=False)
    app.dependency_overrides[current_user] = lambda: CurrentUser(__import__("uuid").uuid4(), "a@x.test", "ADMIN", None)
    try:
        body = TestClient(app).post("/api/admin/evaluations/run-pending", headers={"Authorization": "Bearer x"}).json()
    finally:
        app.dependency_overrides.clear()
    assert body == {"processed": {"a": "COMPLETED", "b": "FAILED", "c": "COMPLETED"}, "counts": {"COMPLETED": 2, "FAILED": 1}, "waiting": 27, "complete": False}
    assert seen == {"limit": 20, "budget_seconds": 250.0, "workers": 4}


def test_time_budgets_are_consistent_with_the_function_limit_and_the_gemini_settings():
    max_duration = json.loads((Path(__file__).resolve().parents[1] / "vercel.json").read_text())["functions"]["app/main.py"]["maxDuration"]
    assert WORST == gemini_eval.ATTEMPTS * gemini_eval.HTTP_TIMEOUT_S + (gemini_eval.ATTEMPTS - 1) * gemini_eval.BACKOFF_MAX_S
    assert "HTTP_TIMEOUT_S" in inspect.getsource(gemini_eval._real_generate)                    # the constant is what the client really uses
    assert WORST <= evaluation.RUN_PENDING_BUDGET_SECONDS                                       # at least one job can always start
    assert evaluation.RUN_PENDING_BUDGET_SECONDS <= max_duration - 30                           # a press ends with time to spare
    assert WORST <= max_duration - 60                                                           # inline submit / single retry fits too


def test_a_job_another_run_already_owns_is_reported_skipped_not_completed(monkeypatch):
    monkeypatch.setattr(evaluation, "_eligible_ids", lambda limit: ["mine", "theirs"])
    monkeypatch.setattr(evaluation, "_run_job", lambda jid: ("COMPLETED", jid == "mine"))
    assert evaluation.run_pending(limit=20, budget_seconds=250, workers=1) == {"mine": "COMPLETED", "theirs": "SKIPPED"}
