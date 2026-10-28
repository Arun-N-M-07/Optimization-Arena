"""'Run pending' against real tables: bounded batches resume cleanly, retries keep working, and no evaluation or mark is ever duplicated,
even when several admins press at once. Run directly and through the transaction pooler."""
import collections
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app import evaluation
from app.auth import CurrentUser, current_user
from app.gemini_eval import CriterionEval, EvalResponse
from app.main import app


def good(ctx):
    return EvalResponse(criteria=[CriterionEval(criterion=k, marks=m, explanation=f"Reasoned explanation for {k.lower()}.")
                                  for k, m in {"INEFFICIENCY": 4.0, "APPROACH": 3.5, "COMPLEXITY": 4.0, "TRADEOFFS": 3.0}.items()],
                        summary="Solid.", needs_review=False, injection_suspected=False)


class Model:
    """Fake Gemini that also advances a fake clock, so budget behaviour is deterministic."""

    def __init__(self):
        self.calls, self.fail_next, self.delay, self.advance, self.now = collections.Counter(), 0, 0.0, 0.0, 0.0
        self.lock = threading.Lock()

    def __call__(self, ctx):
        with self.lock:
            self.calls[ctx.inefficiency] += 1                  # inefficiency text is unique per seeded report
            fail = self.fail_next > 0
            self.fail_next -= 1 if fail else 0
            self.now += self.advance
        time.sleep(self.delay)
        if fail:
            raise RuntimeError("simulated Gemini outage")
        return good(ctx)


@pytest.fixture
def env(db_url, use_db, monkeypatch, world, raw):
    use_db(db_url, EVALUATION_MODE="inline")
    model = Model()
    monkeypatch.setattr(evaluation, "EVALUATOR", model)
    monkeypatch.setattr(evaluation, "_clock", lambda: model.now)
    app.dependency_overrides[current_user] = lambda: CurrentUser(world["admin"], "a@example.test", "ADMIN", None)

    def seed(n):
        """n submitted reports, each with a PENDING AI job that has never been claimed."""
        for v in range(2, n + 2):
            rid = raw.execute("""insert into public.autopsy_reports (team_id, variant_id, submission_id, version, inefficiency, approach, complexity, tradeoffs,
                                                                     status, submitted_at) values (%s, %s, %s, %s, %s, 'a' , 'b', 'c', 'EVALUATION_PENDING', now()) returning id""",
                               (world["team"], world["variant"], world["submission"], v, f"report-{v}")).fetchone()[0]
            raw.execute("insert into public.report_evaluations (report_id, source, status, model, eval_version) values (%s, 'AI', 'PENDING', 'm', 1)", (rid,))
    yield model, seed, world
    app.dependency_overrides.clear()


def press():
    return TestClient(app).post("/api/admin/evaluations/run-pending", headers={"Authorization": "Bearer x"}).json()


def audit(raw, w):
    """(evaluations, criteria, distinct (evaluation, criterion) pairs, completed evaluations) for this team's reports."""
    return raw.execute("""select count(distinct e.id), count(c.id), count(distinct (c.evaluation_id, c.criterion)) filter (where c.id is not null), count(distinct e.id) filter (where e.status = 'COMPLETED')
                          from public.autopsy_reports r join public.report_evaluations e on e.report_id = r.id left join public.evaluation_criteria c on c.evaluation_id = e.id
                          where r.team_id = %s and e.source = 'AI'""", (w["team"],)).fetchone()


def test_bounded_batches_resume_without_losing_or_duplicating_anything(env, raw, monkeypatch):
    model, seed, w = env
    seed(6)
    model.advance = 60.0                                           # every evaluation 'takes' 60 s of fake time
    first = evaluation.run_pending(limit=20, budget_seconds=250, workers=1)
    assert len(first) == 2                                         # starts at t=0 and t=60; t=120 + 151 s worst case > 250 s
    assert audit(raw, w) == (6, 8, 8, 2)                           # 6 evaluations exist, only 2 scored (4 criteria each)
    untouched = raw.execute("""select count(*) from public.report_evaluations e join public.autopsy_reports r on r.id = e.report_id
                               where r.team_id = %s and e.status = 'PENDING' and e.attempts = 0 and e.started_at is null""", (w["team"],)).fetchone()[0]
    assert untouched == 4                                          # the unstarted ones were never claimed
    while True:                                                    # keep pressing, as an admin would
        again = evaluation.run_pending(limit=20, budget_seconds=250, workers=1)
        if not again:
            break
        assert set(again).isdisjoint(first)                        # already-completed jobs are not selected again
    assert audit(raw, w) == (6, 24, 24, 6) and set(model.calls.values()) == {1}      # every report evaluated exactly once


def test_a_failed_evaluation_counts_as_attempted_and_is_retried_by_the_next_press(env, raw):
    model, seed, w = env
    seed(3)
    model.fail_next = 1
    out = press()
    assert out["counts"] == {"COMPLETED": 2, "FAILED": 1} and out["waiting"] == 0 and out["complete"] is True
    failed = raw.execute("""select e.attempts, e.error from public.report_evaluations e join public.autopsy_reports r on r.id = e.report_id
                            where r.team_id = %s and e.status = 'FAILED'""", (w["team"],)).fetchall()
    assert len(failed) == 1 and failed[0][0] == 1 and "RuntimeError" in failed[0][1]
    assert audit(raw, w) == (3, 8, 8, 2)                           # the failed one wrote no marks
    out = press()
    assert out["counts"] == {"COMPLETED": 1} and audit(raw, w) == (3, 12, 12, 3)
    assert press() == {"processed": {}, "counts": {}, "waiting": 0, "complete": True}


def test_one_press_is_capped_and_says_how_much_is_still_waiting(env, raw):
    model, seed, w = env
    seed(25)
    first = press()
    assert len(first["processed"]) == evaluation.RUN_PENDING_LIMIT == 20 and first["waiting"] == 5 and first["complete"] is False
    second = press()
    assert len(second["processed"]) == 5 and second["waiting"] == 0 and second["complete"] is True
    assert audit(raw, w) == (25, 100, 100, 25) and set(model.calls.values()) == {1}


def test_simultaneous_presses_never_evaluate_or_score_a_job_twice(env, raw):
    model, seed, w = env
    seed(12)
    model.delay = 0.05
    results = []
    threads = [threading.Thread(target=lambda: results.append(press())) for _ in range(4)]       # four admins, 4 workers each
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert set(model.calls.values()) == {1} and sum(model.calls.values()) == 12                    # each report reached the model once
    assert audit(raw, w) == (12, 48, 48, 12)
    completed = [j for r in results for j, s in r["processed"].items() if s == "COMPLETED"]
    assert len(completed) == len(set(completed)) == 12          # each job is reported COMPLETED by exactly one press; the others say SKIPPED
    assert {s for r in results for s in r["processed"].values()} <= {"COMPLETED", "SKIPPED"}


def test_a_job_claimed_by_someone_else_is_skipped_not_stolen(env, raw):
    model, seed, w = env
    seed(2)
    raw.execute("""update public.report_evaluations set started_at = now(), attempts = 1 where id = (
                     select e.id from public.report_evaluations e join public.autopsy_reports r on r.id = e.report_id where r.team_id = %s order by r.version limit 1)""", (w["team"],))
    out = press()
    assert out["counts"] == {"COMPLETED": 1}                      # the live claim (another worker/function) was left alone: it is not eligible
    assert audit(raw, w)[3] == 1 and sum(model.calls.values()) == 1
