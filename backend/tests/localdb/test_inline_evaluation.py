"""EVALUATION_MODE=inline (Vercel): the report is committed BEFORE Gemini runs, a Gemini failure never loses the report,
and admin retry never creates a second evaluation or second set of marks. Run directly and through the transaction pooler."""
import threading
import time
from contextlib import contextmanager

import psycopg
import pytest
from fastapi.testclient import TestClient

from app import evaluation
from app.auth import CurrentUser, current_user
from app.gemini_eval import CriterionEval, EvalResponse
from app.main import app

from .conftest import DIRECT

MARKS = {"INEFFICIENCY": 4.0, "APPROACH": 3.5, "COMPLEXITY": 4.0, "TRADEOFFS": 3.0}


def good(ctx):
    return EvalResponse(criteria=[CriterionEval(criterion=k, marks=v, explanation=f"Reasoned explanation for {k.lower()}.") for k, v in MARKS.items()],
                        summary="Solid report overall.", needs_review=False, injection_suspected=False)


class Evaluator:
    """Stand-in for Gemini. Records calls and what an OUTSIDE connection could see while the model 'was running'."""

    def __init__(self, mode="ok", delay=0.0):
        self.mode, self.delay, self.calls, self.seen = mode, delay, 0, []
        self.lock = threading.Lock()

    def __call__(self, ctx):
        with self.lock:
            self.calls += 1
        with psycopg.connect(DIRECT, autocommit=True) as other:        # a different session: sees only COMMITTED data
            self.seen.append(other.execute("""select r.status::text, e.status from public.autopsy_reports r
                                              join public.report_evaluations e on e.report_id = r.id order by r.created_at desc limit 1""").fetchone())
        time.sleep(self.delay)
        if self.mode == "fail":
            raise RuntimeError("simulated Gemini outage")
        return good(ctx)


@pytest.fixture
def env(db_url, use_db, monkeypatch, world):
    use_db(db_url, EVALUATION_MODE="inline")
    ev = Evaluator()
    monkeypatch.setattr(evaluation, "EVALUATOR", ev)
    state = {"user": CurrentUser(world["participant"], "p@example.test", "PARTICIPANT", world["team"])}
    app.dependency_overrides[current_user] = lambda: state["user"]
    yield ev, state, world
    app.dependency_overrides.clear()


def as_admin(state, w):
    state["user"] = CurrentUser(w["admin"], "a@example.test", "ADMIN", None)


def submit(w):
    return TestClient(app).post(f"/api/participant/variants/{w['variant']}/report/submit", headers={"Authorization": "Bearer x"})


def retry(w):
    return TestClient(app).post(f"/api/admin/reports/{w['report']}/evaluate", headers={"Authorization": "Bearer x"})


def counts(raw, w):
    return raw.execute("""select (select count(*) from public.report_evaluations where report_id = %(r)s),
                                 (select count(*) from public.evaluation_criteria c join public.report_evaluations e on e.id = c.evaluation_id where e.report_id = %(r)s)""",
                       {"r": w["report"]}).fetchone()


def test_report_is_committed_before_gemini_runs_and_a_gemini_outage_keeps_it(env, raw):
    ev, state, w = env
    ev.mode = "fail"
    r = submit(w)
    assert r.status_code == 200 and r.json()["already_submitted"] is False          # the participant is never shown an error
    assert ev.seen == [("EVALUATION_PENDING", "PENDING")]                           # committed and visible to others BEFORE the model call
    status, text_ok = raw.execute("select status::text, inefficiency = %s from public.autopsy_reports where id = %s", ("x" * 40, w["report"])).fetchone()
    assert status == "EVALUATION_PENDING" and text_ok                               # report and its content survived
    e = raw.execute("select status, attempts, error from public.report_evaluations where report_id = %s", (w["report"],)).fetchone()
    assert e[0] == "FAILED" and e[1] == 1 and "RuntimeError" in e[2]
    assert counts(raw, w) == (1, 0)                                                 # no marks were written


def test_admin_retry_completes_once_and_repeat_retries_change_nothing(env, raw):
    ev, state, w = env
    ev.mode = "fail"
    submit(w)
    ev.mode = "ok"
    as_admin(state, w)
    r = retry(w)
    assert r.status_code == 200 and r.json()["status"] == "COMPLETED"
    assert counts(raw, w) == (1, 4)
    assert raw.execute("select status::text from public.autopsy_reports where id = %s", (w["report"],)).fetchone()[0] == "EVALUATED"
    got = dict(raw.execute("select criterion, marks from public.evaluation_criteria c join public.report_evaluations e on e.id = c.evaluation_id where e.report_id = %s", (w["report"],)).fetchall())
    assert {k: float(v) for k, v in got.items()} == MARKS                           # marks are exactly what the rubric/validator produced
    calls = ev.calls
    for _ in range(3):
        assert retry(w).json()["status"] == "COMPLETED"
    assert ev.calls == calls and counts(raw, w) == (1, 4)                           # the model is not called again; no duplicates
    assert TestClient(app).post("/api/admin/evaluations/run-pending", headers={"Authorization": "Bearer x"}).json() == {
        "processed": {}, "counts": {}, "waiting": 0, "complete": True}


def test_successful_inline_submit_scores_in_the_same_request_and_resubmit_is_idempotent(env, raw):
    ev, state, w = env
    first = submit(w).json()
    assert first["report"]["status"] == "EVALUATED" and ev.calls == 1               # response already carries the evaluated state
    again = submit(w).json()
    assert again["already_submitted"] is True and ev.calls == 1 and counts(raw, w) == (1, 4)


def test_concurrent_admin_retries_evaluate_exactly_once(env, raw):
    ev, state, w = env
    ev.mode = "fail"
    submit(w)
    ev.mode, ev.delay, ev.calls = "ok", 0.4, 0
    as_admin(state, w)
    out = []
    threads = [threading.Thread(target=lambda: out.append(retry(w).json()["status"])) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert ev.calls == 1 and counts(raw, w) == (1, 4)
    assert sorted(out).count("COMPLETED") >= 1 and set(out) <= {"COMPLETED", "PENDING"}   # losers saw the live claim, never a second run


def test_a_crashed_inline_run_is_recoverable_but_a_live_claim_is_respected(env, raw):
    """Function killed mid-evaluation (timeout/redeploy): job stays PENDING with started_at set."""
    ev, state, w = env
    ev.mode = "fail"
    submit(w)
    ev.mode, ev.calls = "ok", 0
    as_admin(state, w)
    raw.execute("update public.report_evaluations set status = 'PENDING', started_at = now() where report_id = %s", (w["report"],))
    assert retry(w).json()["status"] == "PENDING" and ev.calls == 0                 # claimed 'just now': another invocation may be running it
    raw.execute("update public.report_evaluations set started_at = now() - interval '6 minutes' where report_id = %s", (w["report"],))
    assert retry(w).json()["status"] == "COMPLETED" and ev.calls == 1 and counts(raw, w) == (1, 4)


def test_attempt_cap_is_unchanged(env, raw):
    """Existing behaviour, recorded so it is a conscious decision: after MAX_ATTEMPTS a FAILED job needs a manual database reset."""
    ev, state, w = env
    ev.mode = "fail"
    submit(w)
    ev.calls = 0
    as_admin(state, w)
    raw.execute("update public.report_evaluations set attempts = %s where report_id = %s", (evaluation.MAX_ATTEMPTS, w["report"]))
    assert retry(w).json()["status"] == "FAILED" and ev.calls == 0
